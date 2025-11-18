#!/usr/bin/env python3
"""
UART 연결 테스트 스크립트
- 포트 존재 확인
- 권한 확인
- 포트 열기 테스트
- 간단한 데이터 읽기 테스트
"""
import os
import sys
import serial
import time

def check_port_exists(port):
    """포트 존재 확인"""
    if os.path.exists(port):
        print(f"✓ Port exists: {port}")
        # 심볼릭 링크인지 확인
        if os.path.islink(port):
            real_path = os.readlink(port)
            print(f"  → Symlink to: {real_path}")
            if os.path.exists(real_path):
                print(f"  → Real path exists: {real_path}")
            else:
                print(f"  ✗ Real path does not exist!")
                return False
        return True
    else:
        print(f"✗ Port does not exist: {port}")
        return False

def check_permissions(port):
    """권한 확인"""
    try:
        stat_info = os.stat(port)
        print(f"✓ Port permissions:")
        print(f"  Owner UID: {stat_info.st_uid}")
        print(f"  Group GID: {stat_info.st_gid}")
        
        # dialout 그룹 확인
        import grp
        try:
            dialout_gid = grp.getgrnam('dialout').gr_gid
            print(f"  dialout GID: {dialout_gid}")
            if stat_info.st_gid == dialout_gid:
                print(f"  ✓ Port is in dialout group")
            else:
                print(f"  ⚠ Port is NOT in dialout group")
        except KeyError:
            print(f"  ⚠ dialout group not found")
        
        # 현재 사용자 그룹 확인
        import pwd
        current_uid = os.getuid()
        current_user = pwd.getpwuid(current_uid).pw_name
        print(f"  Current user: {current_user} (UID: {current_uid})")
        
        # 그룹 목록 확인
        import grp
        user_groups = [g.gr_name for g in grp.getgrall() if current_user in g.gr_mem]
        user_groups.append(grp.getgrgid(os.getgid()).gr_name)  # primary group
        print(f"  User groups: {', '.join(set(user_groups))}")
        
        if 'dialout' in user_groups:
            print(f"  ✓ User is in dialout group")
            return True
        else:
            print(f"  ✗ User is NOT in dialout group")
            print(f"  → Run: sudo usermod -aG dialout {current_user}")
            print(f"  → Then logout and login again")
            return False
            
    except Exception as e:
        print(f"✗ Error checking permissions: {e}")
        return False

def test_port_open(port, baudrate=9600):
    """포트 열기 테스트"""
    print(f"\nTesting port open: {port} @ {baudrate} baud")
    try:
        ser = serial.Serial(port, baudrate=baudrate, timeout=1)
        print(f"✓ Port opened successfully")
        print(f"  Device: {ser.port}")
        print(f"  Baudrate: {ser.baudrate}")
        print(f"  Timeout: {ser.timeout}")
        print(f"  Bytesize: {ser.bytesize}")
        print(f"  Parity: {ser.parity}")
        print(f"  Stopbits: {ser.stopbits}")
        
        # 버퍼 비우기
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        print(f"✓ Buffers cleared")
        
        # 버퍼 상태 확인
        if hasattr(ser, 'in_waiting'):
            bytes_waiting = ser.in_waiting
            print(f"  Bytes waiting: {bytes_waiting}")
        
        ser.close()
        print(f"✓ Port closed successfully")
        return True
        
    except serial.SerialException as e:
        print(f"✗ Failed to open port: {e}")
        if "Permission denied" in str(e):
            print(f"  → Permission issue. Check dialout group membership.")
        elif "No such file or directory" in str(e):
            print(f"  → Port does not exist. Check wiring and UART enable.")
        return False
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_data_receive(port, baudrate=9600, timeout=5):
    """데이터 수신 테스트"""
    print(f"\nTesting data reception (timeout: {timeout}s)...")
    try:
        ser = serial.Serial(port, baudrate=baudrate, timeout=1)
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        
        start_time = time.time()
        received = False
        
        while (time.time() - start_time) < timeout:
            if hasattr(ser, 'in_waiting'):
                bytes_waiting = ser.in_waiting
                if bytes_waiting > 0:
                    print(f"  → {bytes_waiting} bytes waiting in buffer")
            
            line = ser.readline()
            if line:
                received = True
                try:
                    text = line.decode('utf-8', errors='ignore').strip()
                    print(f"✓ Data received: {text[:200]}")
                    return True
                except Exception as e:
                    print(f"  Decode error: {e}")
                    print(f"  Raw bytes: {line[:50]}")
                    return True
            
            time.sleep(0.1)
        
        if not received:
            print(f"✗ No data received in {timeout} seconds")
            print(f"  → Check:")
            print(f"     1. Pico is powered on and running")
            print(f"     2. Pico TX (GP0) → Pi RX (GPIO 15)")
            print(f"     3. Pico RX (GP1) → Pi TX (GPIO 14)")
            print(f"     4. GND connected")
            print(f"     5. Baud rate matches (9600)")
            print(f"     6. Pico code is sending data")
            return False
        
        ser.close()
        return True
        
    except Exception as e:
        print(f"✗ Error during data test: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    port = "/dev/serial0"
    baudrate = 9600
    
    print("=" * 60)
    print("UART Connection Test")
    print("=" * 60)
    print()
    
    # 1. 포트 존재 확인
    print("1. Checking port existence...")
    if not check_port_exists(port):
        print("\n✗ Port check failed. Exiting.")
        return 1
    print()
    
    # 2. 권한 확인
    print("2. Checking permissions...")
    has_permission = check_permissions(port)
    print()
    
    # 3. 포트 열기 테스트
    print("3. Testing port open...")
    if not test_port_open(port, baudrate):
        print("\n✗ Port open test failed. Exiting.")
        return 1
    print()
    
    # 4. 데이터 수신 테스트
    if has_permission:
        print("4. Testing data reception...")
        test_data_receive(port, baudrate, timeout=10)
        print()
    
    print("=" * 60)
    print("Test Complete")
    print("=" * 60)
    
    if not has_permission:
        print("\n⚠ Warning: Permission issue detected.")
        print("  Fix: sudo usermod -aG dialout $USER")
        print("  Then logout and login again")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())

