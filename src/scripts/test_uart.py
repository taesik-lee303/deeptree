#!/usr/bin/env python3
"""UART 직접 테스트 스크립트

Pico에서 데이터가 오는지 직접 확인하는 스크립트입니다.
"""

import serial
import sys
import time

def test_uart(dev="/dev/serial0", baud=9600, timeout=5):
    """UART에서 직접 데이터 읽기 테스트"""
    print(f"Testing UART: {dev} @ {baud} baud")
    print("=" * 60)
    
    try:
        ser = serial.Serial(dev, baudrate=baud, timeout=1)
        print(f"✓ UART port opened: {dev}")
        print(f"  - Baudrate: {ser.baudrate}")
        print(f"  - Timeout: {ser.timeout}")
        print(f"  - Bytesize: {ser.bytesize}")
        print(f"  - Parity: {ser.parity}")
        print(f"  - Stopbits: {ser.stopbits}")
        
        # 버퍼 비우기
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        print("\n✓ Buffers cleared")
        
        print(f"\nWaiting for data (timeout: {timeout} seconds)...")
        print("If no data received, check:")
        print("  1. Pico is powered on and running")
        print("  2. Pico TX → Pi RX (GPIO 15)")
        print("  3. Pico RX → Pi TX (GPIO 14)")
        print("  4. GND connected")
        print("  5. Baud rate matches (9600)")
        print("  6. Serial port permissions")
        print()
        
        start_time = time.time()
        received_any = False
        
        while time.time() - start_time < timeout:
            # 바이트가 대기 중인지 확인
            if ser.in_waiting > 0:
                print(f"  → {ser.in_waiting} bytes waiting in buffer")
            
            # 라인 읽기
            line = ser.readline()
            
            if line:
                received_any = True
                try:
                    text = line.decode("utf-8", errors="ignore").strip()
                    print(f"✓ Data received: {text[:200]}")
                    print(f"  Raw bytes: {line[:50]}")
                except Exception as e:
                    print(f"✓ Data received (decode failed): {line[:50]}")
                    print(f"  Error: {e}")
            else:
                # 1초마다 대기 상태 표시
                elapsed = int(time.time() - start_time)
                if elapsed > 0 and elapsed % 1 == 0:
                    print(f"  Waiting... ({elapsed}s elapsed)", end="\r")
        
        print()  # New line after progress
        
        if not received_any:
            print("\n✗ No data received!")
            print("\nTroubleshooting:")
            print("  1. Check Pico is sending data:")
            print("     - Pico code should use UART TX pin")
            print("     - Pico should be sending JSON lines with \\n")
            print("  2. Check wiring:")
            print("     - Pico GP0 (TX) → Pi GPIO 15 (RX)")
            print("     - Pico GP1 (RX) → Pi GPIO 14 (TX)")
            print("     - GND → GND")
            print("  3. Check permissions:")
            print("     sudo usermod -aG dialout $USER")
            print("     # Then logout and login again")
            print("  4. Try different serial port:")
            print("     python test_uart.py --dev /dev/ttyAMA0")
            return False
        else:
            print("\n✓ UART communication working!")
            return True
            
    except serial.SerialException as e:
        print(f"\n✗ Serial port error: {e}")
        print("\nPossible causes:")
        print("  1. Port doesn't exist: ls -l /dev/serial0")
        print("  2. Permission denied: sudo usermod -aG dialout $USER")
        print("  3. Port already in use: lsof /dev/serial0")
        return False
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        try:
            ser.close()
        except:
            pass


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test UART communication")
    parser.add_argument("--dev", default="/dev/serial0", help="Serial device path")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate")
    parser.add_argument("--timeout", type=int, default=10, help="Timeout in seconds")
    
    args = parser.parse_args()
    
    success = test_uart(args.dev, args.baud, args.timeout)
    sys.exit(0 if success else 1)

