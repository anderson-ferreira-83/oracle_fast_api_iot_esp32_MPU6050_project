# main_usb.py - ESP32 MPU6050 sender over USB serial to local bridge

import gc
import sys
import time

try:
    import ujson as json
except ImportError:
    import json

import machine


CONFIG_FILE = "/device_config.json"
MPU_ADDR = 0x68
AUTH_TOKEN_DEFAULT = "F0xb@m986960440"
MAX_SAMPLE_RATE = 150
MIN_SAMPLE_RATE = 1


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


def _bytes_to_int(h, l):
    v = (h << 8) | l
    if v & 0x8000:
        v = -((65535 - v) + 1)
    return v


def _ts():
    return (time.time() + 946684800) + ((time.ticks_ms() % 1000) / 1000.0)


def _safe_write_line(text):
    try:
        sys.stdout.write(text + "\n")
        try:
            sys.stdout.flush()
        except Exception:
            pass
        return True
    except Exception:
        return False


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
        "ts": round(_ts(), 3),
        "t": round(temp, 1),
        "ax": round(ax, 4),
        "ay": round(ay, 4),
        "az": round(az, 4),
        "gx": round(gx, 2),
        "gy": round(gy, 2),
        "gz": round(gz, 2),
    }


def main():
    cfg = _load_json(CONFIG_FILE, {})
    if not isinstance(cfg, dict):
        cfg = {}

    device_id = str(cfg.get("device_id", "ESP32_MPU6050_ORACLE")).strip() or "ESP32_MPU6050_ORACLE"
    collection_id = str(cfg.get("collection_id", "v5_stream")).strip() or "v5_stream"
    token = str(cfg.get("auth_token", AUTH_TOKEN_DEFAULT)).strip() or AUTH_TOKEN_DEFAULT
    fan_state = str(cfg.get("mode", "RAW")).strip() or "RAW"

    sample_rate = _cfg_int(cfg.get("target_sample_rate", 100), 100)
    if sample_rate < MIN_SAMPLE_RATE:
        sample_rate = MIN_SAMPLE_RATE
    if sample_rate > MAX_SAMPLE_RATE:
        sample_rate = MAX_SAMPLE_RATE

    sends_per_sec = _cfg_int(cfg.get("target_sends_per_sec", 2), 2)
    if sends_per_sec < 1:
        sends_per_sec = 1
    if sends_per_sec > 25:
        sends_per_sec = 25

    batch_size = sample_rate // sends_per_sec
    if batch_size < 1:
        batch_size = 1
    usb_max_batch_size = _cfg_int(cfg.get("usb_max_batch_size", 50), 50)
    if usb_max_batch_size < 1:
        usb_max_batch_size = 1
    if batch_size > usb_max_batch_size:
        batch_size = usb_max_batch_size

    period_ms = int(1000 / sample_rate)
    if period_ms < 1:
        period_ms = 1
    usb_baudrate = _cfg_int(cfg.get("usb_baudrate", 115200), 115200)
    if usb_baudrate < 9600:
        usb_baudrate = 115200

    low_mem_threshold = _cfg_int(cfg.get("low_mem_threshold", 14000), 14000)

    # Aumenta throughput serial para sustentar 100 Hz com lotes JSON.
    try:
        machine.UART(0, baudrate=usb_baudrate)
    except Exception:
        usb_baudrate = 115200

    print("=" * 40)
    print("ESP32 MPU6050 v7.4-usb")
    print("Device: {}".format(device_id))
    print("Rate: {} Hz | Batch: {} | Baud: {}".format(sample_rate, batch_size, usb_baudrate))
    print("=" * 40)

    i2c = machine.I2C(0, scl=machine.Pin(22), sda=machine.Pin(21))
    i2c.writeto(MPU_ADDR, b"\x6B\x00")

    hello = {
        "type": "hello",
        "transport": "USB",
        "device_id": device_id,
        "collection_id": collection_id,
        "auth_token": token,
        "sample_rate": sample_rate,
        "batch_size": batch_size,
        "fan_state": fan_state,
    }
    _safe_write_line(json.dumps(hello, separators=(",", ":")))

    sent_ok = 0
    sent_fail = 0
    sensor_fail = 0
    last_stat = time.ticks_ms()
    next_sample = time.ticks_ms()
    gc_counter = 0
    sample_buffer = []

    while True:
        now = time.ticks_ms()
        if time.ticks_diff(now, next_sample) < 0:
            time.sleep_ms(1)
            continue
        next_sample = time.ticks_add(next_sample, period_ms)

        try:
            sample = _read_mpu(i2c, sample_rate, fan_state)
        except Exception as e:
            sensor_fail += 1
            if sensor_fail <= 3 or (sensor_fail % 20) == 0:
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
            "fan_state": fan_state,
            "batch": sample_buffer,
            "net": {
                "connected": True,
                "connection_type": "USB",
                "ssid": "USB",
                "rssi": 0,
                "last_endpoint": "USB",
            },
        }

        try:
            line = json.dumps(payload_obj, separators=(",", ":"))
            ok = _safe_write_line(line)
        except Exception:
            ok = False

        sample_buffer = []
        payload_obj = None
        sample = None

        if ok:
            sent_ok += 1
        else:
            sent_fail += 1
            if sent_fail <= 3 or (sent_fail % 20) == 0:
                print("[USB] send fail {}".format(sent_fail))

        gc_counter += 1
        if gc_counter >= 8 or gc.mem_free() < low_mem_threshold:
            gc.collect()
            gc_counter = 0

        if time.ticks_diff(now, last_stat) >= 10000:
            print(
                "[STAT] OK:{} FAIL:{} SENSOR_FAIL:{} MEM:{}".format(
                    sent_ok,
                    sent_fail,
                    sensor_fail,
                    gc.mem_free(),
                )
            )
            last_stat = now


main()
