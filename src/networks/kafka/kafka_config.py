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
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import List


def _split_hosts(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


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
        kwargs = {
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


settings = KafkaSettings()
