#!/usr/bin/env python3
"""BLE bridge: receives ESP32 BLE batches (NUS) and forwards to backend /api/ingest."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

try:
    from bleak import BleakClient, BleakScanner
except Exception:
    print("Erro: biblioteca 'bleak' nao encontrada.")
    print("Instale com: py -3.11 -m pip install bleak")
    raise SystemExit(2)


DEFAULT_TOKEN = "F0xb@m986960440"
NUS_TX_CHAR = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # notify from ESP32
NUS_RX_CHAR = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # write to ESP32


def post_json(url: str, payload: Dict[str, Any], token: str, timeout: float = 5.0) -> Tuple[bool, int, Optional[Dict[str, Any]], str]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read() or b""
            status = int(getattr(resp, "status", 0) or 0)
            data = None
            if raw:
                try:
                    data = json.loads(raw.decode("utf-8", errors="ignore"))
                except Exception:
                    data = None
            return status == 200, status, data, ""
    except urllib.error.HTTPError as e:
        return False, int(e.code), None, f"HTTP {e.code}"
    except Exception as e:
        return False, 0, None, str(e)


def extract_command(resp: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(resp, dict):
        return {}
    # BLE command channel keeps only lightweight runtime controls.
    # Network/portal payloads are large and not applicable to BLE transport.
    keys = (
        "target_mode",
        "target_rate",
        "target_sends_per_sec",
        "target_collection_id",
    )
    cmd: Dict[str, Any] = {}
    for k in keys:
        if k in resp:
            cmd[k] = resp[k]
    return cmd


class BLEBridge:
    def __init__(
        self,
        device_name: str,
        backend_url: str,
        auth_token: str,
        tx_char: str = NUS_TX_CHAR,
        rx_char: str = NUS_RX_CHAR,
        scan_timeout: float = 12.0,
        post_timeout: float = 5.0,
        disable_commands: bool = False,
        command_chunk_size: int = 20,
    ) -> None:
        self.device_name = device_name
        self.backend_url = backend_url
        self.auth_token = auth_token
        self.tx_char = tx_char
        self.rx_char = rx_char
        self.scan_timeout = scan_timeout
        self.post_timeout = post_timeout
        self.disable_commands = disable_commands
        self.command_chunk_size = max(20, min(100, int(command_chunk_size)))

        self._line_buf = bytearray()
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=256)
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        self.recv_ok = 0
        self.recv_fail = 0
        self.post_ok = 0
        self.post_fail = 0
        self.last_stat = time.time()

    async def _find_device(self):
        target = self.device_name.strip().lower()
        if not target:
            return None

        def _match(d, _ad):
            n = (d.name or "").strip().lower()
            if not n:
                return False
            return n == target or target in n

        return await BleakScanner.find_device_by_filter(_match, timeout=self.scan_timeout)

    def _on_notify(self, _sender: int, data: bytearray) -> None:
        self._line_buf.extend(bytes(data))
        while True:
            idx = self._line_buf.find(b"\n")
            if idx < 0:
                return
            raw = bytes(self._line_buf[:idx])
            del self._line_buf[: idx + 1]

            line = raw.decode("utf-8", errors="ignore").strip()
            if not line:
                continue

            if self._loop is None:
                continue

            def _put():
                try:
                    if self._queue.full():
                        _ = self._queue.get_nowait()
                    self._queue.put_nowait(line)
                except Exception:
                    pass

            self._loop.call_soon_threadsafe(_put)

    async def _consume(self, client: BleakClient):
        while client.is_connected:
            line = await self._queue.get()

            try:
                payload = json.loads(line)
            except Exception:
                self.recv_fail += 1
                continue

            if not isinstance(payload, dict):
                self.recv_fail += 1
                continue

            # Accept only batch payloads from ESP32.
            if payload.get("type") != "batch" or "batch" not in payload:
                continue

            # Mark transport diagnostics for backend.
            net = payload.get("net")
            if not isinstance(net, dict):
                net = {}
            net["connection_type"] = "BLE"
            net["ssid"] = self.device_name
            payload["net"] = net

            self.recv_ok += 1
            ok, status, resp, err = post_json(
                self.backend_url,
                payload,
                self.auth_token,
                timeout=self.post_timeout,
            )
            if ok:
                self.post_ok += 1
            else:
                self.post_fail += 1
                if self.post_fail <= 3 or (self.post_fail % 10) == 0:
                    print(f"[POST] fail status={status} err={err}")

            if not self.disable_commands and ok:
                cmd = extract_command(resp)
                if cmd:
                    try:
                        msg = json.dumps(cmd, separators=(",", ":")) + "\n"
                        await self._write_line_chunked(client, msg)
                    except Exception as e:
                        print(f"[CMD] write fail: {e}")

            now = time.time()
            if now - self.last_stat >= 10:
                print(
                    "[STAT] RX_OK:{} RX_FAIL:{} POST_OK:{} POST_FAIL:{} Q:{}".format(
                        self.recv_ok,
                        self.recv_fail,
                        self.post_ok,
                        self.post_fail,
                        self._queue.qsize(),
                    )
                )
                self.last_stat = now

    async def run_forever(self):
        self._loop = asyncio.get_running_loop()
        print(f"[BLE] Procurando dispositivo: {self.device_name}")
        print(f"[POST] Backend URL: {self.backend_url}")

        while True:
            dev = await self._find_device()
            if not dev:
                print("[BLE] Dispositivo nao encontrado. Nova tentativa em 2s...")
                await asyncio.sleep(2)
                continue

            print(f"[BLE] Encontrado: {dev.name} ({dev.address})")
            try:
                async with BleakClient(dev, timeout=15.0) as client:
                    self._line_buf = bytearray()
                    while not self._queue.empty():
                        _ = self._queue.get_nowait()

                    print("[BLE] Conectado. Iniciando notify...")
                    await client.start_notify(self.tx_char, self._on_notify)
                    try:
                        # Handshake/keepalive: confirms RX path and helps peripherals
                        # that require first write before treating central as active.
                        await self._write_line_chunked(client, '{"type":"ping"}\n')
                    except Exception as e:
                        print(f"[BLE] Aviso handshake RX: {e}")
                    consumer_task = asyncio.create_task(self._consume(client))

                    while client.is_connected:
                        await asyncio.sleep(1)

                    consumer_task.cancel()
                    try:
                        await consumer_task
                    except Exception:
                        pass

            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[BLE] Erro de sessao: {e}")

            print("[BLE] Desconectado. Reconectando em 2s...")
            await asyncio.sleep(2)

    async def _write_line_chunked(self, client: BleakClient, text: str):
        data = text.encode("utf-8")
        n = len(data)
        p = 0
        while p < n:
            chunk = data[p:p + self.command_chunk_size]
            # Windows stack is more stable with response=True on many adapters.
            await client.write_gatt_char(self.rx_char, chunk, response=True)
            p += len(chunk)
            await asyncio.sleep(0.01)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="BLE (ESP32 NUS) to backend /api/ingest bridge")
    p.add_argument("--device-name", default="ESP32-MPU6050-BLE", help="Nome BLE anunciado pelo ESP32")
    p.add_argument("--backend-url", default="http://127.0.0.1:8000/api/ingest", help="URL local do backend ingest")
    p.add_argument("--auth-token", default=os.getenv("API_AUTH_TOKEN", DEFAULT_TOKEN), help="Bearer token")
    p.add_argument("--scan-timeout", type=float, default=12.0, help="Tempo de scan BLE em segundos")
    p.add_argument("--post-timeout", type=float, default=5.0, help="Timeout HTTP POST em segundos")
    p.add_argument("--tx-char", default=NUS_TX_CHAR, help="UUID da characteristic notify (ESP->PC)")
    p.add_argument("--rx-char", default=NUS_RX_CHAR, help="UUID da characteristic write (PC->ESP)")
    p.add_argument("--disable-commands", action="store_true", help="Nao enviar comandos de volta ao ESP32")
    p.add_argument("--command-chunk-size", type=int, default=20, help="Tamanho do chunk de escrita para RX BLE")
    return p.parse_args()


async def _amain() -> int:
    args = parse_args()
    bridge = BLEBridge(
        device_name=args.device_name,
        backend_url=args.backend_url,
        auth_token=args.auth_token,
        tx_char=args.tx_char,
        rx_char=args.rx_char,
        scan_timeout=args.scan_timeout,
        post_timeout=args.post_timeout,
        disable_commands=args.disable_commands,
        command_chunk_size=args.command_chunk_size,
    )
    await bridge.run_forever()
    return 0


def main() -> int:
    try:
        return asyncio.run(_amain())
    except KeyboardInterrupt:
        print("\nEncerrado pelo usuario.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
