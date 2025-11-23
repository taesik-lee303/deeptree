"""MQTT Publisher for color therapy recommendations.

- Publishes full payload to <topic_base>/total
- Also (optional) publishes Pico-compatible payload to settings.pico_topic: {"r","g","b","intensity"}
"""
from __future__ import annotations
import json, time
from datetime import datetime
from typing import Optional, Dict, Any, Tuple

try:
    import paho.mqtt.client as mqtt
except Exception as e:
    mqtt = None

from networks.mqtt.mqtt_config import settings

class MqttColorPublisher:
    def __init__(self, keepalive: int = 30, publish_hz: float = 5.0):
        if mqtt is None:
            raise RuntimeError("paho-mqtt not installed. Add to requirements and pip install.")
        self.keepalive = keepalive
        self.min_interval = 1.0 / max(0.1, publish_hz)
        self._last_pub_ts = 0.0
        self._last_key: Optional[Tuple] = None

        self.client = mqtt.Client(client_id=f"color-pub-{int(time.time())}")
        if settings.username:
            self.client.username_pw_set(settings.username, settings.password or "")
        if settings.tls:
            self.client.tls_set()
        self.client.will_set(settings.topic_status, payload="offline", qos=1, retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        try:
            self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        except Exception:
            pass

    def connect(self):
        self.client.connect(settings.host, settings.port, keepalive=self.keepalive)
        self.client.loop_start()
        time.sleep(0.1)
        self.client.publish(settings.topic_status, payload="online", qos=1, retain=True)
        return self

    def close(self):
        try:
            self.client.publish(settings.topic_status, payload="offline", qos=1, retain=True)
            time.sleep(0.05)
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass

    def publish_color(self, rec, metrics: Optional[Dict[str, Any]] = None, throttle: bool = True, also_pico: bool = False, to_status: bool = False):
        """
        Publish color therapy recommendation to MQTT.
        
        Args:
            rec: Color recommendation object
            metrics: Optional metrics dictionary
            throttle: Whether to throttle duplicate messages
            also_pico: Whether to also publish to Pico topic
            to_status: If True, publish to topic_status (real-time). If False, publish to topic_total (session end).
        """
        now = time.time()
        key = (tuple(rec.rgb_primary), round(float(rec.intensity), 2), rec.mode)
        if throttle and self._last_key == key and (now - self._last_pub_ts) < self.min_interval:
            return
        self._last_key = key
        self._last_pub_ts = now

        # 새로운 형식으로 메시지 구성
        hr = metrics.get('hr') if metrics else None
        q = metrics.get('q') if metrics else 0.0
        rr = metrics.get('rr') if metrics else None
        
        # datetime 문자열 생성
        dt_str = datetime.fromtimestamp(now).isoformat()
        
        payload = {
            "timestamp": now,
            "datetime": dt_str,
            "hr": float(hr) if hr is not None else None,
            "q": float(q),
            "hr_unit": "BPM",
            "rr": float(rr) if rr is not None else None,
            "rr_unit": "RPM" if rr is not None else None
        }
        
        # None 값 제거
        payload = {k: v for k, v in payload.items() if v is not None}
        
        # 토픽 선택: to_status가 True면 status, False면 total
        topic = settings.topic_status if to_status else settings.topic_total
        
        try:
            result = self.client.publish(topic, json.dumps(payload), qos=1, retain=False)
            if result.rc == 0:
                import logging
                logging.getLogger(__name__).debug(f"MQTT published to {topic}: {len(json.dumps(payload))} bytes")
            else:
                import logging
                logging.getLogger(__name__).warning(f"MQTT publish failed to {topic}: rc={result.rc}")
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"MQTT publish exception to {topic}: {e}")

        if also_pico and settings.pico_topic:
            try:
                r, g, b = list(rec.rgb_primary)
                pico = {"r": int(r), "g": int(g), "b": int(b), "intensity": float(rec.intensity)}
                result = self.client.publish(settings.pico_topic, json.dumps(pico), qos=1, retain=False)
                if result.rc == 0:
                    import logging
                    logging.getLogger(__name__).debug(f"MQTT published to {settings.pico_topic}: {len(json.dumps(pico))} bytes")
                else:
                    import logging
                    logging.getLogger(__name__).warning(f"MQTT publish failed to {settings.pico_topic}: rc={result.rc}")
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"MQTT publish exception to {settings.pico_topic}: {e}")

    def _on_connect(self, client, userdata, flags, rc):
        self.client.publish(settings.topic_status, payload="online", qos=1, retain=True)

    def _on_disconnect(self, client, userdata, rc):
        pass
