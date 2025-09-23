import os
import json
import logging
import serial
from typing import Dict, Optional

logger = logging.getLogger(__name__)

def open_serial() -> serial.Serial:
    port = os.getenv("UART_PORT", "/dev/ttyAMA0")
    baud = int(os.getenv("UART_BAUD", "115200"))
    ser = serial.Serial(
        port=port,
        baudrate=baud,
        timeout=1.0,
        write_timeout=1.0
    )
    logger.info("UART opened on %s @ %d", port, baud)
    return ser

def parse_line(line: str) -> Optional[Dict]:
    line = line.strip()
    if not line:
        return None
    if line.startswith("{") and line.endswith("}"):
        try:
            return json.loads(line)
        except Exception:
            logger.debug("JSON parse failed for: %r", line)
    data = {}
    try:
        for token in line.split(","):
            if not token:
                continue
            if "=" in token:
                k, v = token.split("=", 1)
                k = k.strip()
                v = v.strip()
                if v.isdigit():
                    data[k] = int(v)
                else:
                    try:
                        data[k] = float(v)
                    except ValueError:
                        data[k] = v
        if data:
            return data
    except Exception:
        logger.debug("KV parse failed for: %r", line)
    return None
