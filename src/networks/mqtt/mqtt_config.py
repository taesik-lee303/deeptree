"""Common MQTT config for the project.

Env overrides:
- MQTT_HOST, MQTT_PORT, MQTT_TOPIC_BASE, MQTT_USERNAME, MQTT_PASSWORD, MQTT_TLS
- MQTT_PICO_TOPIC  (default: pico/color)  # Pico receiver topic
"""
from dataclasses import dataclass
import os

@dataclass
class MqttSettings:
    host: str = os.getenv("MQTT_HOST", "host")
    port: int = int(os.getenv("MQTT_PORT", "port"))
    topic_base: str = os.getenv("MQTT_TOPIC_BASE", "taesik/therapy").rstrip("/")
    username: str | None = os.getenv("MQTT_USERNAME") or None
    password: str | None = os.getenv("MQTT_PASSWORD") or None
    tls: bool = os.getenv("MQTT_TLS", "false").lower() in ("1","true","yes")
    pico_topic: str = os.getenv("MQTT_PICO_TOPIC", "pico/color").strip()

    @property
    def topic_color(self) -> str:
        return f"{self.topic_base}/color"
    @property
    def topic_status(self) -> str:
        return f"{self.topic_base}/status"

settings = MqttSettings()
