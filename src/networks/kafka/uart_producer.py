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

        print(f"[Producer] Kafka 연결 시도 중... {settings.bootstrap_servers}")
        try:
            self.producer = KafkaProducer(
                value_serializer=lambda payload: json.dumps(payload).encode(settings.value_encoding),
                **settings.producer_kwargs,
            )
            print("[Producer] Kafka Producer 생성 완료")
        except Exception as exc:
            raise RuntimeError(f"Kafka Producer 생성 실패: {exc}") from exc

        print(f"[Producer] Opening UART port: {self.settings.dev}")
        try:
            self.serial = serial.Serial(
                self.settings.dev,
                baudrate=self.settings.baudrate,
                timeout=1,
            )
            print(f"[Producer] UART port opened: {self.settings.dev} @ {self.settings.baudrate}")
            
            # UART 포트 정보 출력
            print(f"[Producer] UART port info:")
            print(f"  - Device: {self.serial.port}")
            print(f"  - Baudrate: {self.serial.baudrate}")
            print(f"  - Timeout: {self.serial.timeout}")
            print(f"  - Bytesize: {self.serial.bytesize}")
            print(f"  - Parity: {self.serial.parity}")
            print(f"  - Stopbits: {self.serial.stopbits}")
            
            # 버퍼 비우기
            self.serial.reset_input_buffer()
            self.serial.reset_output_buffer()
            print("[Producer] UART buffers cleared")
            
        except Exception as exc:
            raise RuntimeError(f"Failed to open UART ({self.settings.dev}): {exc}") from exc

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
        print("[Producer] Waiting for UART data...")
        print(f"[Producer] UART device: {self.settings.dev}, baudrate: {self.settings.baudrate}")
        print(f"[Producer] Kafka topic: {self.settings.topic}")
        print("[Producer] If no data received, check:")
        print("  - Pico is sending data")
        print("  - UART connection (TX/RX wires)")
        print("  - Baud rate matches (should be 9600)")
        print("  - Serial port permissions: sudo usermod -aG dialout $USER")
        
        last_flush = time.time()
        message_count = 0
        last_log_time = time.time()
        no_data_count = 0
        
        while True:
            try:
                line = self.serial.readline()
                if not line:
                    no_data_count += 1
                    # 10초마다 대기 상태 알림
                    if no_data_count % 10 == 0:
                        print(f"[Producer] Still waiting for UART data... (waited {no_data_count * 0.1:.1f} seconds)")
                        # UART 포트 상태 확인
                        if hasattr(self.serial, 'in_waiting'):
                            bytes_waiting = self.serial.in_waiting
                            if bytes_waiting > 0:
                                print(f"[Producer] WARNING: {bytes_waiting} bytes waiting but readline() returned empty!")
                    continue
                
                # 데이터 수신 성공
                no_data_count = 0
                raw = line.decode(self.settings.encoding, errors="ignore").strip()
                if not raw:
                    continue
                
                # 디버그: 수신한 원본 데이터 로그
                now = time.time()
                if self.debug or message_count == 0 or (now - last_log_time > 10):
                    print(f"[Producer] UART data received: {raw[:200]}")
                    last_log_time = now
                
                payload = self._parse_payload(raw)
                if payload is None:
                    if self.debug:
                        print(f"[Producer] Parse failed, raw: {raw[:100]}")
                    continue
                
                # Kafka로 전송
                self.producer.send(self.settings.topic, payload)
                message_count += 1
                
                # 첫 메시지와 이후 10개마다 로그
                if message_count <= 1 or message_count % 10 == 0:
                    print(f"[Producer] Sent to Kafka ({message_count}): topic={self.settings.topic}")
                    if self.debug:
                        print(f"[Producer] Payload: {json.dumps(payload, ensure_ascii=False)[:200]}")
                
                now = time.time()
                if now - last_flush >= self.settings.flush_interval:
                    try:
                        self.producer.flush(timeout=1.0)
                        last_flush = now
                    except Exception as exc:
                        print(f"[Producer] Flush failed: {exc}")
            except KeyboardInterrupt:
                print("[Producer] Shutdown requested")
                break
            except Exception as exc:
                print(f"[Producer] Error: {exc}")
                import traceback
                traceback.print_exc()
                time.sleep(0.5)
        self.close()

    def _parse_payload(self, raw: str) -> Dict[str, Any] | None:
        try:
            data = json.loads(raw)
        except Exception as exc:
            if self.debug:
                print(f"[Producer] JSON 파싱 실패: {exc} :: {raw[:80]!r}")
            return None

        fields = extract_fields(data)
        payload = {
            "ts": fields.get("ts") or time.time(),
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
        
        # 디버그: 추출된 필드 확인
        if self.debug:
            print(f"[Producer] 추출된 필드: {fields}")
            print(f"[Producer] 생성된 페이로드: {payload}")
        
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
