"""UART 센서 데이터를 Kafka 토픽으로 전송하는 생산자 스크립트.

- networks.uart.uart_receiver.extract_fields 재사용으로 다양한 스키마를 정규화
- pyserial로 UART 포트에서 JSON 라인을 읽고 kafka-python Producer로 전송
- 전송 포맷: JSON 문자열 (원본 필드 + 정규화된 필드 + 수신 시각)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict

try:
    import serial
except Exception as exc:  # pragma: no cover
    serial = None  # type: ignore
    _SERIAL_IMPORT_ERROR = exc
else:
    _SERIAL_IMPORT_ERROR = None

try:
    from kafka import KafkaProducer
except Exception as exc:  # pragma: no cover
    KafkaProducer = None  # type: ignore
    _KAFKA_IMPORT_ERROR = exc
else:
    _KAFKA_IMPORT_ERROR = None

from networks.kafka.kafka_config import settings
from networks.uart.uart_receiver import extract_fields


@dataclass
class ProducerSettings:
    topic: str
    dev: str
    baudrate: int
    encoding: str
    flush_interval: float


class UartKafkaProducer:
    def __init__(self, producer_settings: ProducerSettings, debug: bool = False) -> None:
        if serial is None:
            raise RuntimeError(f"pyserial import 실패: {_SERIAL_IMPORT_ERROR}")
        if KafkaProducer is None:
            raise RuntimeError(f"kafka-python import 실패: {_KAFKA_IMPORT_ERROR}")

        self.settings = producer_settings
        self.debug = debug

        try:
            self.producer = KafkaProducer(
                value_serializer=lambda payload: json.dumps(payload).encode(settings.value_encoding),
                **settings.kafka_kwargs,
            )
        except Exception as exc:
            raise RuntimeError(f"Kafka Producer 생성 실패: {exc}") from exc

        try:
            self.serial = serial.Serial(
                self.settings.dev,
                baudrate=self.settings.baudrate,
                timeout=1,
            )
        except Exception as exc:
            raise RuntimeError(f"UART 열기 실패 ({self.settings.dev}): {exc}") from exc

    def close(self) -> None:
        try:
            self.producer.flush(timeout=2.0)
        except Exception:
            pass
        try:
            self.producer.close(timeout=2.0)
        except Exception:
            pass
        try:
            self.serial.close()
        except Exception:
            pass

    def run(self) -> None:
        last_flush = time.time()
        while True:
            try:
                line = self.serial.readline()
                if not line:
                    continue
                raw = line.decode(self.settings.encoding, errors="ignore").strip()
                if not raw:
                    continue
                payload = self._parse_payload(raw)
                if payload is None:
                    continue
                self.producer.send(self.settings.topic, payload)
                if self.debug:
                    print(f"[KafkaProducer] sent: {payload}")

                now = time.time()
                if now - last_flush >= self.settings.flush_interval:
                    try:
                        self.producer.flush(timeout=1.0)
                        last_flush = now
                    except Exception as exc:
                        print(f"[KafkaProducer] flush 실패: {exc}")
            except KeyboardInterrupt:
                print("[KafkaProducer] 종료 요청")
                break
            except Exception as exc:
                print(f"[KafkaProducer] 오류: {exc}")
                time.sleep(0.5)
        self.close()

    def _parse_payload(self, raw: str) -> Dict[str, Any] | None:
        try:
            data = json.loads(raw)
        except Exception as exc:
            if self.debug:
                print(f"[KafkaProducer] JSON 파싱 실패: {exc} :: {raw[:80]!r}")
            return None

        fields = extract_fields(data)
        payload = {
            "ts": fields.get("ts"),
            "device_id": fields.get("device_id"),
            "temp_c": fields.get("temp_c"),
            "hum": fields.get("hum"),
            "noise": fields.get("noise"),
            "pir": fields.get("pir"),
            "pm1": fields.get("pm1"),
            "pm25": fields.get("pm25"),
            "pm10": fields.get("pm10"),
            "raw": data,
            "ingested_at": time.time(),
        }
        return payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="UART → Kafka 생산자")
    parser.add_argument("--dev", default="/dev/serial0", help="UART 디바이스 경로")
    parser.add_argument("--baud", type=int, default=9600, help="UART Baudrate")
    parser.add_argument(
        "--topic",
        default=settings.sensor_topic,
        help="Kafka 토픽 (기본: settings.sensor_topic)",
    )
    parser.add_argument("--encoding", default="utf-8", help="UART 텍스트 인코딩")
    parser.add_argument(
        "--flush-interval",
        type=float,
        default=1.0,
        help="Kafka flush 간격(초)",
    )
    parser.add_argument("--debug", action="store_true", help="디버그 로그 출력")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    prod_settings = ProducerSettings(
        topic=args.topic,
        dev=args.dev,
        baudrate=args.baud,
        encoding=args.encoding,
        flush_interval=max(0.2, args.flush_interval),
    )
    producer = UartKafkaProducer(prod_settings, debug=args.debug)
    try:
        producer.run()
    finally:
        producer.close()


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(f"실행 중단: {exc}")
        sys.exit(1)
