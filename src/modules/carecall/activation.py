"""CareCall 활성화 조건 관련 유틸리티."""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

try:
    from kafka import KafkaConsumer  # type: ignore
except Exception as exc:  # pragma: no cover
    KafkaConsumer = None  # type: ignore
    _KAFKA_IMPORT_ERROR = exc
else:  # pragma: no cover
    _KAFKA_IMPORT_ERROR = None

from modules.carecall.config import ActivationConfig
from networks.kafka.kafka_config import settings
from networks.uart.uart_receiver import extract_fields


@dataclass(frozen=True)
class ActivationEvent:
    """케어콜 시작을 알리는 이벤트."""

    source: str
    payload: Dict[str, Any] | None = None


class SensorTriggerWatcher:
    """소음/PIR 센서 조합으로 케어콜 시작 조건을 감시."""

    def __init__(self, config: ActivationConfig, on_trigger: Callable[[ActivationEvent], None]):
        self.config = config
        self._callback = on_trigger
        self._logger = logging.getLogger(self.__class__.__name__)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_motion_ts: float = 0.0
        self._last_trigger_ts: float = 0.0

    def start(self) -> bool:
        if KafkaConsumer is None:
            self._logger.warning("KafkaConsumer 사용 불가: %s", _KAFKA_IMPORT_ERROR)
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="carecall-sensor-trigger", daemon=True)
        self._thread.start()
        return True

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        try:
            consumer = KafkaConsumer(
                enable_auto_commit=True,
                value_deserializer=lambda v: v.decode(settings.value_encoding, "ignore"),
                consumer_timeout_ms=1000,
                **settings.kafka_kwargs,
            )
            consumer.subscribe([settings.sensor_topic])
            self._logger.info("Kafka 센서 토픽 구독: %s", settings.sensor_topic)
        except Exception as exc:
            self._logger.warning("KafkaConsumer 초기화 실패: %s", exc)
            return

        try:
            while not self._stop_event.is_set():
                try:
                    records = consumer.poll(timeout_ms=500)
                except Exception as exc:
                    self._logger.warning("Kafka poll 실패: %s", exc)
                    time.sleep(1.0)
                    continue
                if not records:
                    continue
                for batch in records.values():
                    for msg in batch:
                        if self._stop_event.is_set():
                            break
                        raw_value = msg.value
                        payload = self._decode_payload(raw_value)
                        if payload is None:
                            continue
                        noise, pir = self._extract_noise_motion(payload)
                        self._evaluate(noise, pir, payload)
        finally:
            try:
                consumer.close()
            except Exception:
                pass

    def _decode_payload(self, raw: Any) -> Dict[str, Any] | None:
        if raw is None:
            return None
        if isinstance(raw, (bytes, bytearray)):
            try:
                raw = raw.decode(settings.value_encoding, "ignore")
            except Exception:
                return None
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except Exception:
                self._logger.debug("센서 JSON 파싱 실패: %s", raw[:120])
                return None
        if isinstance(raw, dict):
            return raw
        return None

    def _extract_noise_motion(self, payload: Dict[str, Any]) -> tuple[Optional[float], Optional[int]]:
        noise = self._to_float(payload.get("noise"))
        pir = self._to_int01(payload.get("pir"))

        raw = payload.get("raw")
        if (noise is None or (pir is None and self.config.motion_required)) and isinstance(raw, dict):
            fields = extract_fields(raw)
            if noise is None:
                noise = self._to_float(fields.get("noise"))
            if pir is None and self.config.motion_required:
                pir = self._to_int01(fields.get("pir"))
        return noise, pir

    def _evaluate(self, noise: Optional[float], pir: Optional[int], payload: Dict[str, Any]) -> None:
        now = time.time()
        if self.config.motion_required and pir is not None:
            if pir:
                self._last_motion_ts = now
        elif not self.config.motion_required:
            # motion이 필요 없다면 항상 최신값을 유지
            self._last_motion_ts = now

        if noise is None or noise < self.config.noise_threshold:
            return

        if self.config.motion_required:
            if self._last_motion_ts <= 0:
                return
            if now - self._last_motion_ts > self.config.motion_window_sec:
                return

        if self.config.sensor_timeout_sec > 0 and (now - self._last_trigger_ts) < self.config.sensor_timeout_sec:
            return

        self._last_trigger_ts = now
        self._callback(
            ActivationEvent(
                source="sensor",
                payload={
                    "noise": noise,
                    "pir": pir,
                    "timestamp": now,
                    "raw": payload,
                },
            )
        )

    def _to_float(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _to_int01(self, value: Any) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, bool):
            return 1 if value else 0
        if isinstance(value, (int, float)):
            return 1 if value else 0
        if isinstance(value, str):
            s = value.strip().lower()
            if s in {"1", "true", "on", "motion", "triggered", "active"}:
                return 1
            if s in {"0", "false", "off", "idle", "inactive", "clear"}:
                return 0
        return None
