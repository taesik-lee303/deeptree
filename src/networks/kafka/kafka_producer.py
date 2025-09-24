# kafka_producer.py
import json
import logging
from typing import Dict, Optional

try:
    # pip install kafka-python-ng
    from kafka import KafkaProducer as _KafkaProducer
except Exception:
    _KafkaProducer = None


class KafkaProducerClient:
    """
    CareCall에서 감정 이벤트를 내보내는 간단한 Kafka Producer 래퍼.
    settings: EmotionProducerSettings (kafka_config.emotion_settings)
    - settings.enabled: bool
    - settings.topic: str
    - settings.producer_kwargs: dict (bootstrap_servers, client_id, acks, linger_ms, ...)
    """

    def __init__(self, settings):
        self.log = logging.getLogger(self.__class__.__name__)
        self.enabled = bool(getattr(settings, "enabled", False)) and _KafkaProducer is not None
        self.topic = getattr(settings, "topic", "carecall.emotion")
        self.producer = None

        if not self.enabled:
            if _KafkaProducer is None:
                self.log.warning("Kafka library not available; Producer disabled.")
            return

        kwargs: Dict[str, object] = dict(getattr(settings, "producer_kwargs", {}))
        # JSON 직렬화
        kwargs["value_serializer"] = lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8")

        try:
            self.producer = _KafkaProducer(**kwargs)
            self.log.info(f"KafkaProducer ready (topic={self.topic})")
        except Exception as e:
            self.enabled = False
            self.log.error(f"Kafka init failed: {e}")

    def send(self, payload: dict):
        """일반 전송 (payload는 dict)"""
        if not (self.enabled and self.producer):
            return
        try:
            self.producer.send(self.topic, payload)
        except Exception as e:
            self.log.error(f"Kafka send failed: {e}")

    def send_emotion(self, emotion: str):
        """텍스트 없이 감정 라벨만 전송"""
        if emotion:
            self.send({"emotion": str(emotion)})

    def flush_close(self, timeout: float = 2.0):
        if not (self.enabled and self.producer):
            return
        try:
            self.producer.flush(timeout)
        except Exception:
            pass
        try:
            self.producer.close(timeout=timeout)
        except Exception:
            pass
