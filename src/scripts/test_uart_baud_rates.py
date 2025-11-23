#!/usr/bin/env python3
"""
UART baud rate 테스트 스크립트
여러 baud rate로 시도하여 올바른 속도를 찾습니다.
"""
import serial
import sys
import time
import json

def test_baud_rate(dev, baudrate, timeout=3):
    """특정 baud rate로 테스트"""
    try:
        ser = serial.Serial(dev, baudrate=baudrate, timeout=1)
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        
        print(f"  Testing {baudrate:6d} baud...", end=" ", flush=True)
        
        start_time = time.time()
        buffer = b""
        valid_lines = 0
        
        while (time.time() - start_time) < timeout:
            if hasattr(ser, 'in_waiting') and ser.in_waiting > 0:
                chunk = ser.read(ser.in_waiting)
                buffer += chunk
                
                # 완전한 라인 찾기
                while b'\n' in buffer:
                    line_bytes, buffer = buffer.split(b'\n', 1)
                    if line_bytes:
                        try:
                            text = line_bytes.decode('utf-8', errors='replace').strip()
                            if text:
                                # JSON인지 확인
                                try:
                                    json.loads(text)
                                    valid_lines += 1
                                    print(f"✓ Found valid JSON!")
                                    ser.close()
                                    return True, text
                                except:
                                    # JSON은 아니지만 텍스트는 있음
                                    if valid_ascii_ratio(text) > 0.5:
                                        valid_lines += 1
                        except:
                            pass
            
            time.sleep(0.1)
        
        ser.close()
        
        # 바이트 패턴 분석
        if len(buffer) > 0:
            valid_ascii = sum(1 for b in buffer if 32 <= b < 127)
            ratio = valid_ascii / len(buffer) if len(buffer) > 0 else 0
            if ratio > 0.3:
                print(f"  Partial data ({ratio:.0%} ASCII)")
                return False, None
            else:
                print(f"  No valid data")
                return False, None
        else:
            print(f"  No data")
            return False, None
            
    except Exception as e:
        print(f"  Error: {e}")
        return False, None

def valid_ascii_ratio(text):
    """텍스트에서 유효한 ASCII 문자의 비율"""
    if not text:
        return 0
    valid = sum(1 for c in text if 32 <= ord(c) < 127)
    return valid / len(text)

def main():
    dev = "/dev/serial0"
    if len(sys.argv) > 1:
        dev = sys.argv[1]
    
    # 일반적인 baud rate 목록
    baud_rates = [115200, 57600, 38400, 19200, 9600, 4800, 2400, 1200]
    
    print("=" * 60)
    print("UART Baud Rate Test")
    print("=" * 60)
    print(f"Device: {dev}")
    print(f"Testing common baud rates...")
    print()
    
    for baud in baud_rates:
        success, data = test_baud_rate(dev, baud, timeout=5)
        if success:
            print()
            print("=" * 60)
            print(f"✓ CORRECT BAUD RATE FOUND: {baud}")
            print("=" * 60)
            print(f"Sample data:")
            print(data[:200])
            print()
            print(f"Use this baud rate:")
            print(f"  python -m networks.uart.uart_receiver --dev {dev} --baud {baud}")
            return 0
    
    print()
    print("=" * 60)
    print("✗ No valid data found at any baud rate")
    print("=" * 60)
    print()
    print("Possible causes:")
    print("  1. Pico is not sending data")
    print("  2. UART wiring issue (TX/RX swapped or loose)")
    print("  3. Pico code not running")
    print("  4. Wrong UART port")
    print()
    print("Check:")
    print("  - Pico is powered on")
    print("  - Pico TX (GP0) → Pi RX (GPIO 15)")
    print("  - Pico RX (GP1) → Pi TX (GPIO 14)")
    print("  - GND connected")
    print("  - Pico code is running")
    
    return 1

if __name__ == "__main__":
    sys.exit(main())

