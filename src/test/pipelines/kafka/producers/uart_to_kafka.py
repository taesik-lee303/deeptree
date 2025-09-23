import os
import time
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv, find_dotenv

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("uart_to_kafka")

ROOT = Path(__file__).resolve().parents[3]  
load_dotenv(ROOT / ".env") or load_dotenv(find_dotenv(usecwd=True))

def main():
    load_dotenv()
    from connectors.uart.uart_io import open_serial, parse_line
    from common.kafka.kafka_utils import build_producer, send_json
    from common.schema.schema_utils import validate
    from common.normalize.normalize_utils import normalize_dict

    prefix = os.getenv("TOPIC_PREFIX", "deepcare")
    device_id = os.getenv("DEVICE_ID", "pi5-uart-bridge")
    schema_version = os.getenv("SCHEMA_VERSION", "v1")
    out_topic = f"{prefix}.sensor-events"
    schema_file = f"sensor-events.{schema_version}.json"

    logger.info("Starting UART → Kafka bridge (topic=%s, device_id=%s)", out_topic, device_id)

    ser = open_serial()
    producer = build_producer()

    running = True
    def _shutdown(sig=None, frame=None):
        nonlocal running
        running = False
    try:
        import signal
        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)
    except Exception:
        pass

    while running:
        try:
            raw_bytes = ser.readline()
            if not raw_bytes:
                continue
            raw = raw_bytes.decode("utf-8", errors="ignore")
            parsed = parse_line(raw)
            if not parsed:
                logger.debug("Skip unparsable line: %r", raw.strip())
                continue

            sensors, extras = normalize_dict(parsed)
            if not sensors:
                logger.debug("No canonical keys in: %r", raw.strip())
                continue

            event = {
                "device_id": device_id,
                "ts": datetime.now(timezone.utc).isoformat(),
                "sensors": sensors,
                "meta": {"src": "uart", "raw_len": len(raw)}
            }
            if extras:
                event["sensors"]["extra"] = extras

            try:
                validate(event, schema_file)
            except Exception as e:
                logger.warning("Schema validation failed, skipping: %s | event=%s", e, json.dumps(event, ensure_ascii=False))
                continue

            send_json(producer, out_topic, event, key=device_id)
        except Exception as e:
            logger.exception("Loop error: %s", e)
            time.sleep(0.5)

    logger.info("Shutting down...")
    try:
        producer.flush(5)
    except Exception:
        pass
    try:
        ser.close()
    except Exception:
        pass

if __name__ == "__main__":
    main()
