import os
import logging
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
import uvicorn

logging.basicConfig(
    level=os.getenv("LOG_LEVEL","INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s"
)
logger = logging.getLogger("http_to_kafka")

app = FastAPI(title="DeepCare HTTP Ingest")

_producer = None
_out_topic = None
_schema_file = None
_default_device = None
_token = None

def init_once():
    global _producer, _out_topic, _schema_file, _default_device, _token
    if _producer is not None:
        return
    load_dotenv()
    from common.kafka.kafka_utils import build_producer
    prefix = os.getenv("TOPIC_PREFIX", "deepcare")
    schema_version = os.getenv("SCHEMA_VERSION", "v1")
    _out_topic = f"{prefix}.sensor-events"
    _schema_file = f"sensor-events.{schema_version}.json"
    _default_device = os.getenv("DEVICE_ID","pi5-http-bridge")
    _token = os.getenv("HTTP_INGEST_TOKEN","") or None
    _producer = build_producer()

@app.post("/ingest")
async def ingest(request: Request):
    init_once()
    if _token:
        token = request.headers.get("x-api-token")
        if token is None or token != _token:
            raise HTTPException(status_code=401, detail="invalid token")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be object")
    sensors_in = payload.get("sensors") if isinstance(payload.get("sensors"), dict) else payload
    extras = {}
    if sensors_in is not payload:
        extras = {k:v for k,v in payload.items() if k not in ("sensors","device_id","ts")}

    from common.normalize.normalize_utils import normalize_dict
    from common.schema.schema_utils import validate
    from common.kafka.kafka_utils import send_json

    sensors, extra2 = normalize_dict(sensors_in)
    extras.update(extra2)
    if not sensors:
        raise HTTPException(status_code=400, detail="no valid sensor keys")

    device_id = str(payload.get("device_id") or _default_device)

    event = {
        "device_id": device_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "sensors": sensors,
        "meta": {"src":"http"}
    }
    if extras:
        event["sensors"]["extra"] = extras

    try:
        validate(event, _schema_file)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"schema validation failed: {e}")

    send_json(_producer, _out_topic, event, key=device_id)
    return {"status":"ok"}

def main():
    load_dotenv()
    host = os.getenv("HTTP_HOST","0.0.0.0")
    port = int(os.getenv("HTTP_PORT","8080"))
    uvicorn.run("pipelines.kafka.producers.http_to_kafka:app", host=host, port=port, reload=False)

if __name__ == "__main__":
    main()
