# main_ble.py - ESP32 MPU6050 sender over BLE (NUS) to local bridge

import gc
import struct
import time

try:
    import ujson as json
except ImportError:
    import json

import machine
import ubluetooth as bluetooth


CONFIG_FILE = "/device_config.json"
MPU_ADDR = 0x68
AUTH_TOKEN_DEFAULT = "F0xb@m986960440"
MAX_SAMPLE_RATE = 150
MIN_BATCH_SIZE = 1
TARGET_SENDS_PER_SEC = 1


# BLE/NUS constants
_IRQ_CENTRAL_CONNECT = 1
_IRQ_CENTRAL_DISCONNECT = 2
_IRQ_GATTS_WRITE = 3

_FLAG_READ = 0x0002
_FLAG_WRITE_NO_RESPONSE = 0x0004
_FLAG_WRITE = 0x0008
_FLAG_NOTIFY = 0x0010

_ADV_TYPE_FLAGS = 0x01
_ADV_TYPE_NAME = 0x09
_ADV_TYPE_UUID128_COMPLETE = 0x07

_UART_UUID = bluetooth.UUID("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
_UART_TX = (
    bluetooth.UUID("6E400003-B5A3-F393-E0A9-E50E24DCCA9E"),
    _FLAG_READ | _FLAG_NOTIFY,
)
_UART_RX = (
    bluetooth.UUID("6E400002-B5A3-F393-E0A9-E50E24DCCA9E"),
    _FLAG_WRITE | _FLAG_WRITE_NO_RESPONSE,
)
_UART_SERVICE = (_UART_UUID, (_UART_TX, _UART_RX))


def _load_json(path, default):
    try:
        with open(path, "r") as f:
            return json.loads(f.read())
    except Exception:
        return default


def _cfg_int(value, default):
    try:
        return int(value)
    except Exception:
        return default


def _cfg_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) != 0
    if isinstance(value, str):
        t = value.strip().lower()
        if t in ("1", "true", "yes", "on"):
            return True
        if t in ("0", "false", "no", "off"):
            return False
    return default


def _bytes_to_int(h, l):
    v = (h << 8) | l
    if v & 0x8000:
        v = -((65535 - v) + 1)
    return v


def _ts():
    # unix timestamp (Micropython epoch starts at 2000)
    return (time.time() + 946684800) + ((time.ticks_ms() % 1000) / 1000.0)


def _read_mpu(i2c, sample_rate, fan_state):
    raw = i2c.readfrom_mem(MPU_ADDR, 0x3B, 14)
    ax = _bytes_to_int(raw[0], raw[1]) / 16384.0
    ay = _bytes_to_int(raw[2], raw[3]) / 16384.0
    az = _bytes_to_int(raw[4], raw[5]) / 16384.0
    temp = _bytes_to_int(raw[6], raw[7]) / 340.0 + 36.53
    gx = _bytes_to_int(raw[8], raw[9]) / 131.0
    gy = _bytes_to_int(raw[10], raw[11]) / 131.0
    gz = _bytes_to_int(raw[12], raw[13]) / 131.0

    return {
        "ts": _ts(),
        "t": round(temp, 1),
        "ax": round(ax, 4),
        "ay": round(ay, 4),
        "az": round(az, 4),
        "gx": round(gx, 2),
        "gy": round(gy, 2),
        "gz": round(gz, 2),
        "sr": sample_rate,
        "fs": fan_state,
    }


def _adv_payload(name=None, services=None, max_len=31):
    payload = bytearray()

    def _append(adv_type, value):
        nonlocal payload
        field = struct.pack("BB", len(value) + 1, adv_type) + value
        if len(payload) + len(field) > max_len:
            return False
        payload.extend(field)
        return True

    _append(_ADV_TYPE_FLAGS, struct.pack("B", 0x06))

    if name:
        # Keep name visible for scanner; trim if needed.
        name_bytes = name.encode()
        max_name_bytes = max_len - len(payload) - 2  # len + type
        if max_name_bytes > 0:
            if len(name_bytes) > max_name_bytes:
                name_bytes = name_bytes[:max_name_bytes]
            _append(_ADV_TYPE_NAME, name_bytes)

    # 128-bit UUID is optional in adv and often does not fit with full name.
    if services:
        for uuid in services:
            b = bytes(uuid)
            if len(b) == 16:
                _append(_ADV_TYPE_UUID128_COMPLETE, b)
    return payload


class BLEUART:
    def __init__(self, name="ESP32-MPU6050-BLE", chunk_size=120, notify_gap_ms=12, notify_retries=5):
        self._ble = bluetooth.BLE()
        self._ble.active(True)
        self._ble.irq(self._irq)

        ((self._tx_handle, self._rx_handle),) = self._ble.gatts_register_services((_UART_SERVICE,))
        self._ble.gatts_set_buffer(self._rx_handle, 512, True)

        self._conn_handle = None
        self._rx_buf = b""
        self._rx_lines = []
        self._chunk_size = chunk_size
        self._notify_gap_ms = notify_gap_ms
        self._notify_retries = notify_retries
        self._name = name

        self._payload = _adv_payload(name=name, services=[_UART_UUID])
        self._advertise()

    def _advertise(self):
        self._ble.gap_advertise(500000, adv_data=self._payload)

    def _irq(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            conn_handle, _, _ = data
            self._conn_handle = conn_handle
            print("[BLE] Central connected")
        elif event == _IRQ_CENTRAL_DISCONNECT:
            self._conn_handle = None
            print("[BLE] Central disconnected")
            self._advertise()
        elif event == _IRQ_GATTS_WRITE:
            conn_handle, value_handle = data
            if value_handle == self._rx_handle:
                # Some stacks may deliver write before we processed connect IRQ.
                if self._conn_handle is None:
                    self._conn_handle = conn_handle
                    print("[BLE] Central connected (via RX write)")
                raw = self._ble.gatts_read(self._rx_handle)
                if raw:
                    self._rx_buf += raw
                    while b"\n" in self._rx_buf:
                        idx = self._rx_buf.find(b"\n")
                        line = self._rx_buf[:idx]
                        self._rx_buf = self._rx_buf[idx + 1:]
                        try:
                            self._rx_lines.append(line.decode("utf-8").strip())
                        except Exception:
                            pass

    def is_connected(self):
        return self._conn_handle is not None

    def pop_rx_line(self):
        if self._rx_lines:
            return self._rx_lines.pop(0)
        return None

    def send_line(self, text):
        if not self.is_connected():
            return False
        if not text:
            return True

        data = text.encode("utf-8") + b"\n"
        n = len(data)
        p = 0
        last_err = None
        try:
            while p < n:
                chunk = data[p:p + self._chunk_size]
                sent = False
                for _ in range(self._notify_retries):
                    if not self.is_connected():
                        return False
                    try:
                        self._ble.gatts_notify(self._conn_handle, self._tx_handle, chunk)
                        sent = True
                        break
                    except Exception as e:
                        last_err = e
                        time.sleep_ms(max(5, self._notify_gap_ms))
                if not sent:
                    if last_err is not None:
                        print("[BLE] notify err {}".format(last_err))
                    return False
                p += len(chunk)
                time.sleep_ms(max(4, self._notify_gap_ms))
            return True
        except Exception:
            return False


def _apply_command(cmd, state):
    if not isinstance(cmd, dict):
        return state

    fan_state = state["fan_state"]
    sample_rate = state["sample_rate"]
    sends_per_sec = state["sends_per_sec"]
    collection_id = state["collection_id"]
    changed = False

    if "target_mode" in cmd:
        v = str(cmd.get("target_mode", "")).strip()
        if v and v != fan_state:
            fan_state = v
            print("[MODE] {}".format(fan_state))
            changed = True

    if "target_collection_id" in cmd:
        v = str(cmd.get("target_collection_id", "")).strip()
        if v and v != collection_id:
            collection_id = v
            print("[COL] {}".format(collection_id))
            changed = True

    if "target_rate" in cmd:
        try:
            v = int(cmd.get("target_rate", 0))
        except Exception:
            v = 0
        if 1 <= v <= MAX_SAMPLE_RATE and v != sample_rate:
            sample_rate = v
            print("[RATE] {} Hz".format(sample_rate))
            changed = True

    if "target_sends_per_sec" in cmd:
        try:
            v = int(cmd.get("target_sends_per_sec", 0))
        except Exception:
            v = 0
        if 1 <= v <= 10 and v != sends_per_sec:
            sends_per_sec = v
            print("[SPS] {} sends/s".format(sends_per_sec))
            changed = True

    if not changed:
        return state

    return {
        "fan_state": fan_state,
        "sample_rate": sample_rate,
        "sends_per_sec": sends_per_sec,
        "collection_id": collection_id,
    }


def main():
    cfg = _load_json(CONFIG_FILE, {})
    if not isinstance(cfg, dict):
        cfg = {}

    device_id = str(cfg.get("device_id", "ESP32_MPU6050_ORACLE")).strip() or "ESP32_MPU6050_ORACLE"
    collection_id = str(cfg.get("collection_id", "v5_stream")).strip() or "v5_stream"
    token = str(cfg.get("auth_token", AUTH_TOKEN_DEFAULT)).strip() or AUTH_TOKEN_DEFAULT
    ble_name = str(cfg.get("ble_device_name", "ESP32-MPU6050-BLE")).strip() or "ESP32-MPU6050-BLE"

    sample_rate = _cfg_int(cfg.get("target_sample_rate", 15), 15)
    if sample_rate < 1:
        sample_rate = 1
    if sample_rate > MAX_SAMPLE_RATE:
        sample_rate = MAX_SAMPLE_RATE

    ble_max_sample_rate = _cfg_int(cfg.get("ble_max_sample_rate", 10), 10)
    if ble_max_sample_rate < 1:
        ble_max_sample_rate = 1
    if sample_rate > ble_max_sample_rate:
        sample_rate = ble_max_sample_rate

    sends_per_sec = _cfg_int(cfg.get("target_sends_per_sec", TARGET_SENDS_PER_SEC), TARGET_SENDS_PER_SEC)
    if sends_per_sec < 1:
        sends_per_sec = 1
    if sends_per_sec > 10:
        sends_per_sec = 10
    ble_max_sends_per_sec = _cfg_int(cfg.get("ble_max_sends_per_sec", 2), 2)
    if ble_max_sends_per_sec < 1:
        ble_max_sends_per_sec = 1
    if sends_per_sec > ble_max_sends_per_sec:
        sends_per_sec = ble_max_sends_per_sec

    batch_size = max(MIN_BATCH_SIZE, sample_rate // sends_per_sec)
    ble_max_batch_size = _cfg_int(cfg.get("ble_max_batch_size", 8), 8)
    if ble_max_batch_size < 1:
        ble_max_batch_size = 1
    if batch_size > ble_max_batch_size:
        batch_size = ble_max_batch_size
    chunk_size = _cfg_int(cfg.get("ble_notify_chunk_size", 120), 120)
    if chunk_size < 20:
        chunk_size = 20
    if chunk_size > 180:
        chunk_size = 180
    notify_gap_ms = _cfg_int(cfg.get("ble_notify_gap_ms", 12), 12)
    if notify_gap_ms < 4:
        notify_gap_ms = 4
    if notify_gap_ms > 80:
        notify_gap_ms = 80
    notify_retries = _cfg_int(cfg.get("ble_notify_retries", 5), 5)
    if notify_retries < 1:
        notify_retries = 1
    if notify_retries > 12:
        notify_retries = 12

    allow_commands = _cfg_bool(cfg.get("ble_allow_commands", True), True)
    fan_state = str(cfg.get("mode", "RAW")).strip() or "RAW"

    print("=" * 40)
    print("ESP32 MPU6050 v7.4-ble")
    print("BLE name: {}".format(ble_name))
    print("Device: {}".format(device_id))
    print("Rate: {} Hz | Batch: {} | Chunk: {}".format(sample_rate, batch_size, chunk_size))
    print("=" * 40)

    i2c = machine.I2C(0, scl=machine.Pin(22), sda=machine.Pin(21))
    i2c.writeto(MPU_ADDR, b"\x6B\x00")

    ble = BLEUART(
        name=ble_name,
        chunk_size=chunk_size,
        notify_gap_ms=notify_gap_ms,
        notify_retries=notify_retries,
    )

    hello = {
        "type": "hello",
        "device_id": device_id,
        "collection_id": collection_id,
        "auth_token": token,
    }
    ble.send_line(json.dumps(hello))
    last_conn_state = ble.is_connected()

    period_ms = int(1000 / sample_rate)
    next_sample = time.ticks_ms()

    sent_ok = 0
    sent_fail = 0
    dropped_no_central = 0
    last_stat = time.ticks_ms()
    sample_buffer = []
    gc_counter = 0
    low_mem_threshold = _cfg_int(cfg.get("low_mem_threshold", 14000), 14000)

    state = {
        "fan_state": fan_state,
        "sample_rate": sample_rate,
        "sends_per_sec": sends_per_sec,
        "collection_id": collection_id,
    }

    while True:
        conn_state = ble.is_connected()
        if conn_state and not last_conn_state:
            ble.send_line(json.dumps(hello))
        last_conn_state = conn_state

        # Optional command channel from bridge/backend.
        if allow_commands:
            line = ble.pop_rx_line()
            if line:
                try:
                    cmd = json.loads(line)
                    new_state = _apply_command(cmd, state)
                    if new_state is not state:
                        state = new_state
                        sample_rate = state["sample_rate"]
                        sends_per_sec = state["sends_per_sec"]
                        batch_size = max(MIN_BATCH_SIZE, sample_rate // sends_per_sec)
                        period_ms = int(1000 / sample_rate)
                        collection_id = state["collection_id"]
                        fan_state = state["fan_state"]
                except Exception:
                    pass

        now = time.ticks_ms()
        if time.ticks_diff(now, next_sample) < 0:
            time.sleep_ms(1)
            continue
        next_sample = time.ticks_add(next_sample, period_ms)

        if not ble.is_connected():
            # No central connected: do not flood send failures.
            if time.ticks_diff(now, last_stat) >= 10000:
                mem = gc.mem_free()
                print(
                    "[STAT] OK:{} FAIL:{} DROP:{} CONN:{} MEM:{}".format(
                        sent_ok,
                        sent_fail,
                        dropped_no_central,
                        0,
                        mem,
                    )
                )
                last_stat = now
            time.sleep_ms(20)
            continue

        try:
            sample = _read_mpu(i2c, sample_rate, fan_state)
        except Exception as e:
            print("[SENSOR] {}".format(e))
            gc.collect()
            continue

        sample_buffer.append(sample)
        if len(sample_buffer) < batch_size:
            continue

        payload_obj = {
            "type": "batch",
            "device_id": device_id,
            "collection_id": collection_id,
            "sample_rate": sample_rate,
            "batch": sample_buffer,
            "net": {
                "connected": ble.is_connected(),
                "connection_type": "BLE",
                "ssid": ble_name,
                "rssi": 0,
                "last_endpoint": "BLE",
            },
        }

        try:
            msg = json.dumps(payload_obj)
        except Exception as e:
            print("[PAYLOAD] {}".format(e))
            sample_buffer = []
            gc.collect()
            continue

        sample_buffer = []
        if ble.send_line(msg):
            sent_ok += 1
        else:
            sent_fail += 1
            if not ble.is_connected():
                dropped_no_central += 1
            if sent_fail <= 3 or (sent_fail % 10) == 0:
                print("[BLE] send fail {}".format(sent_fail))

        payload_obj = None
        sample = None
        gc_counter += 1
        if gc_counter >= 5 or gc.mem_free() < low_mem_threshold:
            gc.collect()
            gc_counter = 0

        if time.ticks_diff(now, last_stat) >= 10000:
            mem = gc.mem_free()
            print(
                "[STAT] OK:{} FAIL:{} DROP:{} CONN:{} MEM:{}".format(
                    sent_ok,
                    sent_fail,
                    dropped_no_central,
                    1 if ble.is_connected() else 0,
                    mem,
                )
            )
            last_stat = now


main()
