# ===== Pi5: uart_receiver.py (flexible schema) =====
import json
import time
import argparse
import serial

def pick(d, keys, default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default

def to_int01(v):
    # normalize PIR/IR -> 0/1
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (int, float)):
        return 1 if v else 0
    if isinstance(v, str):
        s = v.strip().lower()
        s_compact = "".join(ch for ch in s if ch.isalnum())
        if s in ("1", "true", "on", "motion", "triggered", "active", "object detected", "detected"):
            return 1
        if s in ("0", "false", "off", "clear", "idle", "inactive", "object not detected", "no object", "absent"):
            return 0
        if s_compact in ("1", "true", "on", "motion", "triggered", "active", "objectdetected", "detected"):
            return 1
        if s_compact in ("0", "false", "off", "clear", "idle", "inactive", "objectnotdetected", "noobject", "absent"):
            return 0
    return None

def extract_fields(data):
    """
    data는 피코가 보낸 dict.
    1) {"sensors": {...}} 형태도 지원
    2) {"dht22": {...}, "ir": {...}, "sound": {...}, "pm": {...}} 형태도 지원
    """
    ts = data.get("ts")
    device_id = data.get("device_id")

    # 1) 공통 섹션 후보 구성
    if "sensors" in data and isinstance(data["sensors"], dict):
        base = data["sensors"]
    else:
        base = data  # top-level에 모듈별 dict가 있는 형태

    # 섹션별 dict
    dht = base.get("dht22", {}) if isinstance(base.get("dht22", {}), dict) else {}
    ir  = base.get("ir", {})    if isinstance(base.get("ir", {}), dict)    else {}
    snd = base.get("sound", {}) if isinstance(base.get("sound", {}), dict) else {}
    pm  = base.get("pm", {})    if isinstance(base.get("pm", {}), dict)    else {}

    # 온도/습도 후보 키
    temp = pick(dht, ["temp_c", "temperature", "temp", "t"])
    hum  = pick(dht, ["hum", "humidity", "h"])

    # 소음 후보 키
    noise = pick(snd, ["noise_raw", "noise", "value", "raw", "level", "noise_level"])

    # IR/PIR 후보 키 (문자/불리언/숫자 모두 받아서 0/1로 정규화)
    pir = None
    pir_candidates = [
        pick(ir, ["pir", "motion", "value", "status"]),
        pick(base, ["pir", "motion"]),  # sensors 루트에 평평하게 들어오는 경우
    ]
    for v in pir_candidates:
        x = to_int01(v)
        if x is not None:
            pir = x
            break

    # PM(미세먼지) 후보 키
    pm25 = pick(pm, ["pm25", "pm2_5", "pm2.5", "pm_2_5"])
    pm10 = pick(pm, ["pm10", "pm_10"])
    pm1  = pick(pm, ["pm1", "pm1_0", "pm_1_0"])

    return {
        "ts": ts,
        "device_id": device_id,
        "temp_c": temp,
        "hum": hum,
        "noise": noise,
        "pir": pir,
        "pm1": pm1,
        "pm25": pm25,
        "pm10": pm10,
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", default="/dev/serial0")
    ap.add_argument("--baud", type=int, default=9600)  # ← 피코 uart_module과 동일하게!
    ap.add_argument("--timeout", type=int, default=30, help="Timeout in seconds (0 = infinite)")
    args = ap.parse_args()

    print(f"Opening UART: {args.dev} @ {args.baud} baud")
    try:
        ser = serial.Serial(args.dev, baudrate=args.baud, timeout=1)
        print(f"✓ UART port opened successfully")
        print(f"  Device: {ser.port}")
        print(f"  Baudrate: {ser.baudrate}")
        print(f"  Timeout: {ser.timeout}")
        
        # 버퍼 비우기
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        print("✓ Buffers cleared")
        
        print(f"\nListening for data... (timeout: {args.timeout}s, 0=infinite)")
        print("If no data received, check:")
        print("  1. Pico is powered on and running")
        print("  2. Pico TX (GP0) → Pi RX (GPIO 15)")
        print("  3. Pico RX (GP1) → Pi TX (GPIO 14)")
        print("  4. GND connected")
        print("  5. Baud rate matches (9600)")
        print("  6. Serial port permissions")
        print()
        
    except serial.SerialException as e:
        print(f"✗ Failed to open serial port: {e}")
        print("\nTroubleshooting:")
        print("  1. Check port exists: ls -l /dev/serial0")
        print("  2. Check permissions: sudo usermod -aG dialout $USER")
        print("  3. Check if port is in use: lsof /dev/serial0")
        return
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return

    start_time = time.time()
    no_data_count = 0
    received_any = False

    while True:
        try:
            # 타임아웃 체크
            if args.timeout > 0 and (time.time() - start_time) > args.timeout:
                print(f"\nTimeout reached ({args.timeout}s)")
                if not received_any:
                    print("✗ No data received during timeout period")
                    print("\nPossible causes:")
                    print("  1. Pico is not sending data")
                    print("  2. UART wiring issue")
                    print("  3. Wrong baud rate")
                    print("  4. Pico code not running")
                break
            
            # 바이트 대기 확인
            if hasattr(ser, 'in_waiting'):
                bytes_waiting = ser.in_waiting
                if bytes_waiting > 0:
                    print(f"[DEBUG] {bytes_waiting} bytes waiting in buffer")
            
            line = ser.readline()
            
            if not line:
                no_data_count += 1
                # 5초마다 대기 상태 알림
                if no_data_count % 5 == 0:
                    elapsed = int(time.time() - start_time)
                    print(f"  Waiting... ({elapsed}s elapsed, {no_data_count} empty reads)", end="\r")
                continue
            
            # 데이터 수신 성공
            no_data_count = 0
            received_any = True
            s = line.decode("utf-8", errors="ignore").strip()
            
            if not s:
                continue
            
            print(f"\n✓ Data received: {s[:200]}")
            
            try:
                data = json.loads(s)
                print(f"✓ JSON parsed successfully")
            except Exception as e:
                print(f"✗ JSON parse error: {e}")
                print(f"  Raw data: {s[:120]}")
                continue

            fields = extract_fields(data)
            print(f"✓ Fields extracted: {fields}")

            # 보기 좋게 요약 출력 (없는 건 생략)
            parts = []
            if fields["ts"] is not None: parts.append(str(fields["ts"]))
            if fields["device_id"] is not None: parts.append(f"device={fields['device_id']}")
            if fields["temp_c"] is not None: parts.append(f"T={fields['temp_c']}°C")
            if fields["hum"] is not None: parts.append(f"H={fields['hum']}%")
            if fields["noise"] is not None: parts.append(f"noise={fields['noise']}")
            if fields["pir"] is not None: parts.append(f"pir={fields['pir']}")
            if fields["pm1"] is not None: parts.append(f"pm1={fields['pm1']}")
            if fields["pm25"] is not None: parts.append(f"pm25={fields['pm25']}")
            if fields["pm10"] is not None: parts.append(f"pm10={fields['pm10']}")

            if parts:
                print("  → " + " | ".join(parts))
            else:
                # 필드가 하나도 안 뽑히면 원본 한 줄 보여주기
                print(f"  [RAW] {s}")

        except KeyboardInterrupt:
            print("\n\nInterrupted by user")
            break
        except Exception as e:
            print(f"\n[UART ERR] {e}")
            import traceback
            traceback.print_exc()
            time.sleep(0.3)
    
    ser.close()
    if received_any:
        print("\n✓ UART communication test completed successfully")
    else:
        print("\n✗ No data received. Check Pico and UART connection.")

if __name__ == "__main__":
    main()
