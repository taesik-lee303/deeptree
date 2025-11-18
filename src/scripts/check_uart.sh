#!/bin/bash
# UART 포트 상태 확인 스크립트

echo "=== UART Port Check ==="
echo

# 1. 포트 존재 확인
echo "1. Checking if /dev/serial0 exists..."
if [ -e /dev/serial0 ]; then
    echo "   ✓ /dev/serial0 exists"
    ls -l /dev/serial0
else
    echo "   ✗ /dev/serial0 does not exist"
    echo "   Checking /dev/ttyAMA0..."
    if [ -e /dev/ttyAMA0 ]; then
        echo "   ✓ /dev/ttyAMA0 exists"
        ls -l /dev/ttyAMA0
    else
        echo "   ✗ /dev/ttyAMA0 does not exist"
    fi
fi
echo

# 2. 권한 확인
echo "2. Checking user permissions..."
if groups | grep -q dialout; then
    echo "   ✓ User is in dialout group"
else
    echo "   ✗ User is NOT in dialout group"
    echo "   Run: sudo usermod -aG dialout $USER"
    echo "   Then logout and login again"
fi
echo

# 3. 포트 사용 중인지 확인
echo "3. Checking if port is in use..."
if command -v lsof &> /dev/null; then
    if lsof /dev/serial0 2>/dev/null | grep -q .; then
        echo "   ⚠ Port is in use:"
        lsof /dev/serial0 2>/dev/null | grep -v WARNING
    else
        echo "   ✓ Port is not in use"
    fi
else
    echo "   (lsof not available, skipping)"
fi
echo

# 4. UART 활성화 확인
echo "4. Checking UART configuration..."
if [ -f /boot/firmware/config.txt ] || [ -f /boot/config.txt ]; then
    CONFIG_FILE=$(ls /boot/firmware/config.txt /boot/config.txt 2>/dev/null | head -1)
    if grep -q "enable_uart=1" "$CONFIG_FILE" 2>/dev/null; then
        echo "   ✓ UART is enabled in config.txt"
    else
        echo "   ⚠ UART may not be enabled"
        echo "   Run: sudo raspi-config"
        echo "   Interface Options > Serial Port > Enable"
    fi
else
    echo "   (config.txt not found, may not be Raspberry Pi)"
fi
echo

# 5. 시리얼 포트 정보
echo "5. Serial port information..."
if command -v dmesg &> /dev/null; then
    echo "   Recent UART-related messages:"
    dmesg | grep -i "tty\|uart\|serial" | tail -5
else
    echo "   (dmesg not available)"
fi
echo

echo "=== Check Complete ==="
echo
echo "Next steps:"
echo "  1. If port exists and permissions OK, try:"
echo "     python -m networks.uart.uart_receiver --dev /dev/serial0 --baud 9600 --timeout 30"
echo "  2. If port doesn't exist, check wiring and enable UART in raspi-config"
echo "  3. If permission denied, add user to dialout group and re-login"

