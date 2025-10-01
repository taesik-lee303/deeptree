#!/usr/bin/env python3
"""통신 프로토콜 건강 상태를 점검하는 진단용 런처."""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional


@dataclass
class CheckResult:
    name: str
    success: bool
    detail: str
    suggestion: Optional[str] = None

    def render(self) -> str:
        status = "OK" if self.success else "FAIL"
        line = f"[{status:4s}] {self.name}: {self.detail}"
        if self.suggestion and not self.success:
            line += f"\n        → {self.suggestion}"
        return line


def check_mqtt(timeout: float) -> CheckResult:
    try:
        from networks.mqtt import mqtt_publisher
    except Exception as exc:
        return CheckResult(
            name="mqtt",
            success=False,
            detail=f"모듈 임포트 실패: {exc}",
            suggestion="paho-mqtt 등이 설치됐는지 확인하세요.",
        )

    settings = mqtt_publisher.settings
    try:
        publisher = mqtt_publisher.MqttColorPublisher(keepalive=int(timeout * 2) or 5, publish_hz=1.0)
    except Exception as exc:
        return CheckResult(
            name="mqtt",
            success=False,
            detail=f"퍼블리셔 초기화 실패: {exc}",
            suggestion="패키지 설치 및 인증 정보를 다시 확인하세요.",
        )

    try:
        publisher.connect()
    except Exception as exc:
        return CheckResult(
            name="mqtt",
            success=False,
            detail=f"브로커 연결 실패: {exc}",
            suggestion=f"MQTT_HOST/PORT 설정과 네트워크 경로를 점검하세요 (topic={settings.topic_base}).",
        )

    try:
        payload = {
            "diagnostic": True,
            "ts": int(time.time()),
            "client": "network_diagnostics",
        }
        publisher.client.publish(settings.topic_status, json.dumps(payload), qos=0, retain=False)
    except Exception as exc:
        publisher.close()
        return CheckResult(
            name="mqtt",
            success=False,
            detail=f"진단 메시지 발행 실패: {exc}",
            suggestion="브로커 권한 또는 토픽 설정을 확인하세요.",
        )

    publisher.close()
    return CheckResult(
        name="mqtt",
        success=True,
        detail=f"{settings.host}:{settings.port} 연결 및 상태 메시지 전송 완료",
    )


def check_kafka_producer(timeout: float, send_probe: bool) -> CheckResult:
    try:
        from kafka import KafkaProducer  # type: ignore
    except Exception as exc:
        return CheckResult(
            name="kafka-producer",
            success=False,
            detail=f"kafka-python 불러오기 실패: {exc}",
            suggestion="pip install kafka-python-ng 등을 통해 의존성을 설치하세요.",
        )

    from networks.kafka.kafka_config import emotion_settings

    kwargs = dict(emotion_settings.producer_kwargs)
    kwargs.setdefault("value_serializer", lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"))

    try:
        producer = KafkaProducer(**kwargs)
    except Exception as exc:
        return CheckResult(
            name="kafka-producer",
            success=False,
            detail=f"프로듀서 생성 실패: {exc}",
            suggestion="KAFKA_BOOTSTRAP_SERVERS 및 인증 정보를 확인하세요.",
        )

    try:
        end = time.time() + max(timeout, 1.0)
        connected = False
        while time.time() < end:
            if producer.bootstrap_connected():
                connected = True
                break
            time.sleep(0.2)
        if not connected:
            return CheckResult(
                name="kafka-producer",
                success=False,
                detail="부트스트랩 브로커에 연결되지 않음",
                suggestion="브로커 주소와 방화벽을 확인하거나 --timeout 값을 늘려보세요.",
            )

        if send_probe:
            future = producer.send(
                emotion_settings.topic,
                {
                    "diagnostic": True,
                    "ts": int(time.time()),
                    "client": "network_diagnostics",
                },
            )
            future.get(timeout=max(3.0, timeout))
            detail = f"{emotion_settings.topic} 토픽으로 테스트 메시지 전송 완료"
        else:
            detail = "부트스트랩 연결 정상 (메시지 전송은 생략)"

        return CheckResult(name="kafka-producer", success=True, detail=detail)
    except Exception as exc:
        return CheckResult(
            name="kafka-producer",
            success=False,
            detail=f"운영 테스트 실패: {exc}",
            suggestion="토픽 존재 여부와 브로커 로그를 확인하세요.",
        )
    finally:
        try:
            producer.close()
        except Exception:
            pass


def check_kafka_consumer(timeout: float) -> CheckResult:
    try:
        from kafka import KafkaConsumer  # type: ignore
    except Exception as exc:
        return CheckResult(
            name="kafka-consumer",
            success=False,
            detail=f"kafka-python 불러오기 실패: {exc}",
            suggestion="pip install kafka-python-ng 등을 통해 의존성을 설치하세요.",
        )

    from networks.kafka.kafka_config import settings

    kwargs = dict(settings.kafka_kwargs)
    kwargs.setdefault("consumer_timeout_ms", int(max(timeout, 1.0) * 1000))

    try:
        consumer = KafkaConsumer(settings.sensor_topic, **kwargs)
    except Exception as exc:
        return CheckResult(
            name="kafka-consumer",
            success=False,
            detail=f"컨슈머 생성 실패: {exc}",
            suggestion="그룹 아이디, 인증, 오프셋 설정을 확인하세요.",
        )

    try:
        consumer.poll(timeout_ms=int(max(timeout, 1.0) * 1000))
        return CheckResult(
            name="kafka-consumer",
            success=True,
            detail=f"{settings.sensor_topic} 토픽에 구독 연결 성공",
        )
    except Exception as exc:
        return CheckResult(
            name="kafka-consumer",
            success=False,
            detail=f"폴링 실패: {exc}",
            suggestion="토픽 접근 권한 또는 브로커 상태를 점검하세요.",
        )
    finally:
        try:
            consumer.close()
        except Exception:
            pass


def check_uart(port: Optional[str], baud: int, try_open: bool) -> CheckResult:
    try:
        import serial  # type: ignore
    except Exception as exc:
        return CheckResult(
            name="uart",
            success=False,
            detail=f"pyserial 임포트 실패: {exc}",
            suggestion="pip install pyserial 후 다시 시도하세요.",
        )

    if not (try_open and port):
        return CheckResult(
            name="uart",
            success=True,
            detail="pyserial 사용 가능 (포트 연결 검사는 생략)",
        )

    try:
        ser = serial.Serial(port, baudrate=baud, timeout=1)
        ser.close()
        return CheckResult(
            name="uart",
            success=True,
            detail=f"{port} @ {baud} 연결 가능",
        )
    except Exception as exc:
        return CheckResult(
            name="uart",
            success=False,
            detail=f"시리얼 포트 열기 실패: {exc}",
            suggestion="장치 연결 상태와 권한을 확인하세요.",
        )


CHECKS: Dict[str, Callable[..., CheckResult]] = {
    "mqtt": check_mqtt,
    "kafka-producer": check_kafka_producer,
    "kafka-consumer": check_kafka_consumer,
    "uart": check_uart,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="networks 패키지 통신 프로토콜을 점검합니다.",
    )
    parser.add_argument(
        "--check",
        dest="checks",
        action="append",
        choices=tuple(CHECKS.keys()),
        help="수행할 검사 이름 (반복 사용 가능). 지정하지 않으면 모든 검사를 실행.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="네트워크 검사 타임아웃(초).",
    )
    parser.add_argument(
        "--send-kafka-probe",
        action="store_true",
        help="카프카 프로듀서가 실제 진단 메시지를 토픽에 발행하도록 합니다.",
    )
    parser.add_argument(
        "--uart-port",
        type=str,
        help="점검할 UART 포트 경로. 지정 시 --try-open과 함께 사용하면 포트를 실제로 엽니다.",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=9600,
        help="UART 검사 시 사용할 보레이트.",
    )
    parser.add_argument(
        "--try-open",
        action="store_true",
        help="UART 포트를 실제로 열어 연결 가능 여부를 확인합니다.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    selected = args.checks or list(CHECKS.keys())
    results: List[CheckResult] = []

    for name in selected:
        if name == "mqtt":
            results.append(check_mqtt(args.timeout))
        elif name == "kafka-producer":
            results.append(check_kafka_producer(args.timeout, send_probe=args.send_kafka_probe))
        elif name == "kafka-consumer":
            results.append(check_kafka_consumer(args.timeout))
        elif name == "uart":
            results.append(check_uart(args.uart_port, args.baud, args.try_open))

    print("\n=== 네트워크 진단 결과 ===")
    for result in results:
        print(result.render())

    failures = [r for r in results if not r.success]
    if failures:
        print(f"\n총 {len(failures)}개 검사가 실패했습니다. 위 제안 사항을 참고하세요.")
        return 1

    print("\n모든 검사가 정상적으로 통과했습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
