import json
import os
import logging
from typing import Any, Dict, Optional
from kafka import KafkaProducer
from kafka.errors import KafkaError

logger = logging.getLogger(__name__)

def get_bootstrap_servers() -> str:
    return os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")

def json_serializer(obj: Dict[str, Any]) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

def build_producer() -> KafkaProducer:
    producer = KafkaProducer(
        bootstrap_servers=get_bootstrap_servers(),
        value_serializer=json_serializer,
        acks="all",
        linger_ms=5,
        retries=10,
        max_in_flight_requests_per_connection=1,
        request_timeout_ms=30000,
        connections_max_idle_ms=540000
    )
    logger.info("KafkaProducer created (bootstrap=%s)", get_bootstrap_servers())
    return producer

def send_json(producer: KafkaProducer, topic: str, payload: Dict[str, Any], key: Optional[str] = None) -> None:
    future = producer.send(topic, value=payload, key=(key.encode("utf-8") if key else None))
    try:
        metadata = future.get(timeout=10)
        logger.debug("Produced to %s [%d] @ %d", metadata.topic, metadata.partition, metadata.offset)
    except KafkaError as e:
        logger.exception("Failed to produce message to %s: %s", topic, e)
        raise
