import os
import json
import logging
from datetime import datetime, timezone

from dotenv import load_dotenv
import paho.mqtt.client as mqtt

logging.basicConfig(
    level=os.getenv("LOG_LEVEL","INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s"
)
logger = logging.getLogger("mqtt_to_kafka")

def try_parse_payload(payload: bytes):
    s = payload.decode("utf-8", errors="ignore").strip()
    if not s:
        return None
    if s.startswith("{") and s.endswith("}"):
        try:
            return json.loads(s)
        except Exception:
            pass
    try:
        from connectors.uart.uart_io import parse_line
        return parse_line(s)
    except Exception:
        return None

def extract_device_id(topic: str, payload_dict: dict, fallback: str) -> str:
    if isinstance(payload_dict, dict) and "device_id" in payload_dict and str(payload_dict["device_id"]).strip():
        return str(payload_dict["device_id"]).strip()
    parts = topic.split("/")
    if len(parts) >= 2 and parts[0] in ("sensors", "sensor", "devices"):
        return parts[1]
    return fallback

def main():
    load_dotenv()
    from common.kafka.kafka_utils import build_producer, send_json
    from common.schema.schema_utils import validate
    from common.normalize.normalize_utils import normalize_dict

    prefix = os.getenv("TOPIC_PREFIX", "deepcare")
    schema_version = os.getenv("SCHEMA_VERSION", "v1")
    out_topic = f"{prefix}.sensor-events"
    schema_file = f"sensor-events.{schema_version}.json"

    broker = os.getenv("MQTT_BROKER","localhost")
    port = int(os.getenv("MQTT_PORT","1883"))
    username = os.getenv("MQTT_USERNAME","") or None
    password = os.getenv("MQTT_PASSWORD","") or None
    client_id = os.getenv("MQTT_CLIENT_ID","deepcare-mqtt-bridge")
    topics = [t.strip() for t in os.getenv("MQTT_TOPICS","sensors/#").split(",") if t.strip()]
    fallback_device = os.getenv("DEVICE_ID","pi5-mqtt-bridge")

    producer = build_producer()

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            logger.info("Connected to MQTT %s:%d", broker, port)
            for t in topics:
                client.subscribe(t, qos=1)
                logger.info("Subscribed: %s", t)
        else:
            logger.error("MQTT connect failed rc=%s", rc)

    def on_message(client, userdata, msg):
        try:
            parsed = try_parse_payload(msg.payload)
            if not parsed:
                logger.debug("Skip unparsable MQTT payload on %s", msg.topic)
                return
            sensors, extras = normalize_dict(parsed)
            if not sensors:
                logger.debug("No canonical keys on %s", msg.topic)
                return

            device_id = extract_device_id(msg.topic, parsed, fallback_device)

            event = {
                "device_id": device_id,
                "ts": datetime.now(timezone.utc).isoformat(),
                "sensors": sensors,
                "meta": {"src":"mqtt","topic": msg.topic, "qos": msg.qos}
            }
            if extras:
                event["sensors"]["extra"] = extras

            try:
                validate(event, schema_file)
            except Exception as e:
                logger.warning("Schema validation failed: %s | event=%s", e, json.dumps(event, ensure_ascii=False))
                return

            send_json(producer, out_topic, event, key=device_id)
        except Exception as e:
            logger.exception("on_message error: %s", e)

    client = mqtt.Client(client_id=client_id, clean_session=True)
    if username:
        client.username_pw_set(username, password=password)

    client.on_connect = on_connect
    client.on_message = on_message

    logger.info("Connecting to MQTT %s:%d ...", broker, port)
    client.connect(broker, port, keepalive=30)
    client.loop_forever(retry_first_connection=True)

if __name__ == "__main__":
    main()
