"""Kafka 관련 공통 설정.

환경 변수:
- KAFKA_BOOTSTRAP_SERVERS (쉼표 구분, 기본: localhost:9092)
- KAFKA_SENSOR_TOPIC (기본: sensors.uart)
- KAFKA_GROUP_ID (기본: uart-display)
- KAFKA_SECURITY_PROTOCOL (기본: PLAINTEXT)
- KAFKA_SASL_MECHANISM / KAFKA_SASL_USERNAME / KAFKA_SASL_PASSWORD
- KAFKA_OFFSET_RESET (기본: latest)
- KAFKA_VALUE_ENCODING (기본: utf-8)
- DISPLAY_REFRESH_HZ (기본: 1.0)
- DISPLAY_FONT_PATH (선택)
- DISPLAY_DIAMETER_PIXELS (기본: 480)

[케어콜 감정 이벤트용 프로듀서]
- KAFKA_EMO_ENABLED (기본: 1)                  # 0이면 비활성
- KAFKA_EMO_TOPIC (기본: carecall.emotion)
- KAFKA_EMO_CLIENT_ID (기본: carecall-edge)
- KAFKA_EMO_ACKS (기본: 0)                     # 0|1|all
- KAFKA_EMO_LINGER_MS (기본: 20)
- KAFKA_EMO_BATCH_SIZE (선택, 기본: 16384)
- KAFKA_EMO_COMPRESSION (선택: gzip|snappy|lz4|zstd)
# 보안/접속 관련은 상단 공용 변수(KAFKA_BOOTSTRAP_SERVERS, ... )를 그대로 사용
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import List, Dict, Any


def _split_hosts(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


# =========================
# 기존(소비자/표시) 설정 유지
# =========================
@dataclass
class KafkaSettings:
    bootstrap_servers: List[str] = field(
        default_factory=lambda: _split_hosts(os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"))
    )
    sensor_topic: str = os.getenv("KAFKA_SENSOR_TOPIC", "sensors.uart")
    group_id: str = os.getenv("KAFKA_GROUP_ID", "uart-display")
    security_protocol: str = os.getenv("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT")
    sasl_mechanism: str | None = os.getenv("KAFKA_SASL_MECHANISM") or None
    sasl_username: str | None = os.getenv("KAFKA_SASL_USERNAME") or None
    sasl_password: str | None = os.getenv("KAFKA_SASL_PASSWORD") or None
    auto_offset_reset: str = os.getenv("KAFKA_OFFSET_RESET", "latest")
    value_encoding: str = os.getenv("KAFKA_VALUE_ENCODING", "utf-8")
    display_refresh_hz: float = float(os.getenv("DISPLAY_REFRESH_HZ", "1.0"))
    font_path: str | None = os.getenv("DISPLAY_FONT_PATH") or None
    diameter_pixels: int = int(os.getenv("DISPLAY_DIAMETER_PIXELS", "480"))

    @property
    def kafka_kwargs(self) -> dict:
        """Consumer용 설정"""
        kwargs: Dict[str, Any] = {
            "bootstrap_servers": self.bootstrap_servers,
            "group_id": self.group_id or None,
            "auto_offset_reset": self.auto_offset_reset,
            "security_protocol": self.security_protocol,
        }
        if self.sasl_username and self.sasl_password:
            kwargs.update(
                {
                    "sasl_mechanism": self.sasl_mechanism or "PLAIN",
                    "sasl_plain_username": self.sasl_username,
                    "sasl_plain_password": self.sasl_password,
                }
            )
        return kwargs

    @property
    def producer_kwargs(self) -> dict:
        """Producer용 설정 (Consumer 전용 옵션 제외)"""
        kwargs: Dict[str, Any] = {
            "bootstrap_servers": self.bootstrap_servers,
            "security_protocol": self.security_protocol,
        }
        if self.sasl_username and self.sasl_password:
            kwargs.update(
                {
                    "sasl_mechanism": self.sasl_mechanism or "PLAIN",
                    "sasl_plain_username": self.sasl_username,
                    "sasl_plain_password": self.sasl_password,
                }
            )
        return kwargs


# ==========================================
# 케어콜 감정 이벤트(프로듀서) 전용 설정 추가
# ==========================================
@dataclass
class EmotionProducerSettings:
    """케어콜 모듈에서 '대화 텍스트 + 간단 감정' 이벤트를 내보내는 Kafka Producer 설정"""
    # 활성화/토픽/클라이언트
    enabled: bool = os.getenv("KAFKA_EMO_ENABLED", "1") != "0"
    topic: str = os.getenv("KAFKA_EMO_TOPIC", "carecall.emotion")
    client_id: str = os.getenv("KAFKA_EMO_CLIENT_ID", "carecall-edge")

    # 프로듀서 성능/신뢰 옵션
    acks_raw: str = os.getenv("KAFKA_EMO_ACKS", "0")  # "0"|"1"|"all"
    linger_ms: int = int(os.getenv("KAFKA_EMO_LINGER_MS", "20"))
    batch_size: int = int(os.getenv("KAFKA_EMO_BATCH_SIZE", "16384"))
    compression_type: str | None = os.getenv("KAFKA_EMO_COMPRESSION") or None

    # 공용 접속/보안 설정 재사용
    bootstrap_servers: List[str] = field(
        default_factory=lambda: _split_hosts(os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"))
    )
    security_protocol: str = os.getenv("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT")
    sasl_mechanism: str | None = os.getenv("KAFKA_SASL_MECHANISM") or None
    sasl_username: str | None = os.getenv("KAFKA_SASL_USERNAME") or None
    sasl_password: str | None = os.getenv("KAFKA_SASL_PASSWORD") or None

    @property
    def acks(self) -> int | str:
        v = (self.acks_raw or "").strip().lower()
        if v in ("all", "-1"):
            return "all"
        try:
            return int(v)
        except Exception:
            return 0

    @property
    def producer_kwargs(self) -> dict:
        """kafka-python-ng KafkaProducer(**kwargs) 에 바로 전달 가능한 매개변수"""
        kw: Dict[str, Any] = {
            "bootstrap_servers": self.bootstrap_servers,
            "client_id": self.client_id,
            "acks": self.acks,
            "linger_ms": self.linger_ms,
            "batch_size": self.batch_size,
        }
        if self.compression_type:
            kw["compression_type"] = self.compression_type

        # 보안 옵션
        kw["security_protocol"] = self.security_protocol
        if self.sasl_username and self.sasl_password:
            kw.update(
                {
                    "sasl_mechanism": self.sasl_mechanism or "PLAIN",
                    "sasl_plain_username": self.sasl_username,
                    "sasl_plain_password": self.sasl_password,
                }
            )
        return kw


# 모듈 외부에서 가져다 쓰기 쉬운 인스턴스
settings = KafkaSettings()
emotion_settings = EmotionProducerSettings()
