#!/usr/bin/env python3
"""USB serial bridge: receives ESP32 batch JSON lines and forwards to backend /api/ingest."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

try:
    import serial
    from serial.tools import list_ports
except Exception:
    print("Erro: biblioteca 'pyserial' nao encontrada.")
    print("Instale com: py -3.11 -m pip install pyserial")
    raise SystemExit(2)


DEFAULT_TOKEN = "F0xb@m986960440"


def post_json(url: str, payload: Dict[str, Any], token: str, timeout: float = 5.0) -> Tuple[bool, int, str]:
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
            status = int(getattr(resp, "status", 0) or 0)
            _ = resp.read()
            return status == 200, status, ""
    except urllib.error.HTTPError as e:
        return False, int(e.code), f"HTTP {e.code}"
    except Exception as e:
        return False, 0, str(e)


def _port_info_text(p: Any) -> str:
    parts = [
        str(getattr(p, "device", "") or ""),
        str(getattr(p, "description", "") or ""),
        str(getattr(p, "manufacturer", "") or ""),
        str(getattr(p, "product", "") or ""),
        str(getattr(p, "hwid", "") or ""),
    ]
    return " | ".join(parts).strip()


def _looks_like_esp_port(info_text: str, hint: str) -> bool:
    t = info_text.lower()
    k = (
        "cp210",
        "silicon labs",
        "wch",
        "ch340",
        "usb serial",
        "espressif",
        "jtag serial",
        "uart",
    )
    if hint and hint.lower() in t:
        return True
    for item in k:
        if item in t:
            return True
    return False


def choose_serial_port(forced_port: str, hint: str) -> Optional[str]:
    if forced_port:
        return forced_port.strip()

    ports = list(list_ports.comports())
    if not ports:
        return None

    candidates: List[str] = []
    fallback: List[str] = []
    for p in ports:
        info = _port_info_text(p)
        if _looks_like_esp_port(info, hint):
            candidates.append(str(p.device))
        else:
            fallback.append(str(p.device))

    if candidates:
        return candidates[0]
    if fallback:
        return fallback[0]
    return None


def list_ports_human() -> str:
    ports = list(list_ports.comports())
    if not ports:
        return "(nenhuma porta serial detectada)"
    lines = []
    for p in ports:
        lines.append("- {} :: {}".format(p.device, _port_info_text(p)))
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="USB serial (ESP32) to backend /api/ingest bridge")
    p.add_argument("--port", default="", help="Porta serial (ex.: COM7). Vazio = auto-detect")
    p.add_argument("--baudrate", type=int, default=115200, help="Baudrate serial")
    p.add_argument("--read-timeout", type=float, default=0.15, help="Timeout de leitura serial em segundos")
    p.add_argument("--backend-url", default="http://127.0.0.1:8000/api/ingest", help="URL local do backend ingest")
    p.add_argument("--auth-token", default=os.getenv("API_AUTH_TOKEN", DEFAULT_TOKEN), help="Bearer token")
    p.add_argument("--device-hint", default="ESP32", help="Texto para ajudar no auto-detect da porta")
    p.add_argument("--post-timeout", type=float, default=5.0, help="Timeout HTTP POST em segundos")
    p.add_argument("--reconnect-delay", type=float, default=2.0, help="Atraso antes de nova tentativa de reconexao")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.baudrate < 1200:
        print("Baudrate invalido: {}".format(args.baudrate))
        return 2

    print("[USB] Iniciando bridge serial -> backend")
    print("[POST] Backend URL: {}".format(args.backend_url))

    ser: Optional[serial.Serial] = None
    current_port = ""
    rx_ok = 0
    rx_json_fail = 0
    post_ok = 0
    post_fail = 0
    rx_samples_ok = 0
    last_stat = time.time()
    last_not_found_log = 0.0

    rx_buf = bytearray()

    while True:
        try:
            if ser is None or not ser.is_open:
                port = choose_serial_port(args.port, args.device_hint)
                if not port:
                    now = time.time()
                    if now - last_not_found_log >= 5:
                        print("[USB] Porta nao encontrada. Portas detectadas:")
                        print(list_ports_human())
                        last_not_found_log = now
                    time.sleep(max(0.5, args.reconnect_delay))
                    continue

                current_port = port
                print("[USB] Conectando em {} @ {}...".format(current_port, args.baudrate))
                ser = serial.Serial(
                    port=current_port,
                    baudrate=args.baudrate,
                    timeout=args.read_timeout,
                    write_timeout=1,
                )
                try:
                    ser.reset_input_buffer()
                    ser.reset_output_buffer()
                except Exception:
                    pass
                rx_buf = bytearray()
                print("[USB] Conectado. Aguardando lotes JSON...")

            raw = ser.read(4096)
            if not raw:
                now = time.time()
                if now - last_stat >= 10:
                    print(
                        "[STAT] PORT:{} RX_OK:{} RX_JSON_FAIL:{} POST_OK:{} POST_FAIL:{} HZ:{:.1f}".format(
                            current_port,
                            rx_ok,
                            rx_json_fail,
                            post_ok,
                            post_fail,
                            rx_samples_ok / 10.0,
                        )
                    )
                    rx_samples_ok = 0
                    last_stat = now
                continue

            rx_buf.extend(raw)
            if len(rx_buf) > 524288:
                # Protege contra crescimento indefinido caso quebras de linha se percam.
                rx_buf = rx_buf[-262144:]

            while True:
                idx = rx_buf.find(b"\n")
                if idx < 0:
                    break
                line_bytes = bytes(rx_buf[:idx])
                del rx_buf[: idx + 1]

                line = line_bytes.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                if not line.startswith("{"):
                    continue

                try:
                    payload = json.loads(line)
                except Exception:
                    rx_json_fail += 1
                    if rx_json_fail <= 3 or (rx_json_fail % 20) == 0:
                        print("[USB] JSON invalido: {}".format(line[:120]))
                    continue

                if not isinstance(payload, dict):
                    continue

                msg_type = str(payload.get("type", "")).strip().lower()
                if msg_type == "hello":
                    print("[USB] HELLO recebido de {}".format(payload.get("device_id", "ESP32")))
                    continue
                if msg_type != "batch" or "batch" not in payload:
                    continue

                net = payload.get("net")
                if not isinstance(net, dict):
                    net = {}
                net["connection_type"] = "USB"
                net["ssid"] = "USB"
                net["connected"] = True
                payload["net"] = net

                rx_ok += 1
                try:
                    rx_samples_ok += len(payload.get("batch", []))
                except Exception:
                    pass
                ok, status, err = post_json(args.backend_url, payload, args.auth_token, timeout=args.post_timeout)
                if ok:
                    post_ok += 1
                else:
                    post_fail += 1
                    if post_fail <= 3 or (post_fail % 10) == 0:
                        print("[POST] fail status={} err={}".format(status, err))

                now = time.time()
                if now - last_stat >= 10:
                    eff_hz = rx_samples_ok / 10.0
                    print(
                        "[STAT] PORT:{} RX_OK:{} RX_JSON_FAIL:{} POST_OK:{} POST_FAIL:{} HZ:{:.1f}".format(
                            current_port,
                            rx_ok,
                            rx_json_fail,
                            post_ok,
                            post_fail,
                            eff_hz,
                        )
                    )
                    rx_samples_ok = 0
                    last_stat = now

        except KeyboardInterrupt:
            print("\nEncerrado pelo usuario.")
            break
        except serial.SerialException as e:
            print("[USB] SerialException em {}: {}".format(current_port or "porta?", e))
            try:
                if ser is not None:
                    ser.close()
            except Exception:
                pass
            ser = None
            time.sleep(max(0.5, args.reconnect_delay))
        except Exception as e:
            print("[USB] Erro: {}".format(e))
            try:
                if ser is not None:
                    ser.close()
            except Exception:
                pass
            ser = None
            time.sleep(max(0.5, args.reconnect_delay))

    try:
        if ser is not None and ser.is_open:
            ser.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
