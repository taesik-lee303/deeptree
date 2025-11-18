#!/usr/bin/env python3
"""센서 데이터 흐름 디버깅 스크립트

이 스크립트는 센서 데이터가 Pico → UART → Kafka → Display로 
올바르게 전달되는지 확인합니다.
"""

import json
import sys
import time
from pathlib import Path

# 프로젝트 루트를 경로에 추가
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

def check_uart_receiver():
    """UART에서 직접 데이터 수신 확인"""
    print("\n" + "="*60)
    print("1. UART 직접 수신 테스트")
    print("="*60)
    
    try:
        from networks.uart.uart_receiver import extract_fields
        import serial
        
        ser = serial.Serial("/dev/serial0", baudrate=9600, timeout=2)
        print("✓ UART 포트 열기 성공: /dev/serial0 @ 9600")
        print("  데이터 수신 대기 중... (5초)")
        
        start_time = time.time()
        received = False
        
        while time.time() - start_time < 5:
            line = ser.readline()
            if line:
                try:
                    data = json.loads(line.decode("utf-8", errors="ignore").strip())
                    fields = extract_fields(data)
                    print(f"\n✓ 데이터 수신 성공!")
                    print(f"  원본: {json.dumps(data, indent=2, ensure_ascii=False)}")
                    print(f"  추출된 필드: {json.dumps(fields, indent=2, ensure_ascii=False)}")
                    received = True
                    break
                except Exception as e:
                    print(f"  파싱 오류: {e}")
                    print(f"  원본 라인: {line[:100]}")
        
        ser.close()
        
        if not received:
            print("  ⚠ 데이터를 수신하지 못했습니다.")
            print("     - Pico가 데이터를 보내고 있는지 확인")
            print("     - UART 연결 확인")
            return False
        return True
        
    except Exception as e:
        print(f"  ✗ UART 테스트 실패: {e}")
        return False


def check_kafka_connection():
    """Kafka 연결 확인"""
    print("\n" + "="*60)
    print("2. Kafka 연결 테스트")
    print("="*60)
    
    try:
        from kafka import KafkaProducer, KafkaConsumer
        from networks.kafka.kafka_config import settings
        
        bootstrap = settings.bootstrap_servers
        print(f"  Bootstrap 서버: {bootstrap}")
        
        # Producer 테스트
        try:
            producer = KafkaProducer(**settings.producer_kwargs)
            producer.close(timeout=2)
            print("  ✓ Kafka Producer 연결 성공")
        except Exception as e:
            print(f"  ✗ Kafka Producer 연결 실패: {e}")
            return False
        
        # Consumer 테스트
        try:
            consumer = KafkaConsumer(
                bootstrap_servers=bootstrap,
                consumer_timeout_ms=2000,
                auto_offset_reset="latest"
            )
            topics = consumer.list_topics(timeout=5)
            print(f"  ✓ Kafka Consumer 연결 성공")
            print(f"  사용 가능한 토픽: {list(topics.keys())}")
            consumer.close()
        except Exception as e:
            print(f"  ✗ Kafka Consumer 연결 실패: {e}")
            return False
        
        return True
        
    except ImportError as e:
        print(f"  ✗ Kafka 라이브러리 import 실패: {e}")
        return False
    except Exception as e:
        print(f"  ✗ Kafka 테스트 실패: {e}")
        return False


def check_kafka_topic_data():
    """Kafka 토픽에서 데이터 확인"""
    print("\n" + "="*60)
    print("3. Kafka 토픽 데이터 확인")
    print("="*60)
    
    try:
        from kafka import KafkaConsumer
        from networks.kafka.kafka_config import settings
        
        topic = settings.sensor_topic
        print(f"  토픽: {topic}")
        print(f"  Bootstrap: {settings.bootstrap_servers}")
        print("  최근 메시지 확인 중... (5초)")
        
        consumer = KafkaConsumer(
            topic,
            bootstrap_servers=settings.bootstrap_servers,
            auto_offset_reset="latest",
            consumer_timeout_ms=5000,
            value_deserializer=lambda m: m.decode("utf-8", errors="ignore") if isinstance(m, (bytes, bytearray)) else m
        )
        
        received = False
        for message in consumer:
            try:
                if isinstance(message.value, str):
                    data = json.loads(message.value)
                else:
                    data = message.value
                
                print(f"\n✓ Kafka에서 데이터 수신!")
                print(f"  토픽: {message.topic}")
                print(f"  파티션: {message.partition}")
                print(f"  오프셋: {message.offset}")
                print(f"  데이터: {json.dumps(data, indent=2, ensure_ascii=False)}")
                received = True
                break
            except Exception as e:
                print(f"  파싱 오류: {e}")
        
        consumer.close()
        
        if not received:
            print("  ⚠ Kafka 토픽에서 데이터를 수신하지 못했습니다.")
            print("     - UART Producer가 실행 중인지 확인")
            print("     - 토픽 이름 확인: " + topic)
            return False
        return True
        
    except Exception as e:
        print(f"  ✗ Kafka 토픽 테스트 실패: {e}")
        return False


def check_sensor_display_parsing():
    """Sensor Display의 데이터 파싱 확인"""
    print("\n" + "="*60)
    print("4. Sensor Display 데이터 파싱 테스트")
    print("="*60)
    
    try:
        from modules.display.sensor_display import extract_sensor_values, apply_aliases
        
        # 테스트 데이터 (Pico에서 보내는 형식)
        test_cases = [
            {
                "name": "표준 형식 (sensors 래핑)",
                "data": {
                    "ts": 1234567890,
                    "device_id": "pico-001",
                    "sensors": {
                        "dht22": {"temp_c": 23.5, "hum": 45.0},
                        "sound": {"noise": 500},
                        "ir": {"pir": 1},
                        "pm": {"pm25": 15, "pm10": 25}
                    }
                }
            },
            {
                "name": "플랫 형식",
                "data": {
                    "ts": 1234567890,
                    "device_id": "pico-001",
                    "dht22": {"temp_c": 23.5, "hum": 45.0},
                    "sound": {"noise": 500},
                    "ir": {"pir": 1},
                    "pm": {"pm25": 15, "pm10": 25}
                }
            },
            {
                "name": "UART Producer 형식",
                "data": {
                    "ts": 1234567890,
                    "device_id": "pico-001",
                    "temp_c": 23.5,
                    "hum": 45.0,
                    "noise": 500,
                    "pir": 1,
                    "pm25": 15,
                    "pm10": 25,
                    "raw": {}
                }
            }
        ]
        
        for test_case in test_cases:
            print(f"\n  테스트: {test_case['name']}")
            updates = extract_sensor_values(test_case['data'])
            if updates:
                print(f"  ✓ 파싱 성공:")
                for key, value in updates.items():
                    print(f"    {key}: {value}")
            else:
                print(f"  ✗ 파싱 실패: 데이터를 추출하지 못했습니다")
                print(f"    입력 데이터: {json.dumps(test_case['data'], indent=4, ensure_ascii=False)}")
        
        return True
        
    except Exception as e:
        print(f"  ✗ 파싱 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_uart_producer_running():
    """UART Producer 프로세스 확인"""
    print("\n" + "="*60)
    print("5. UART Producer 프로세스 확인")
    print("="*60)
    
    try:
        import subprocess
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if "uart_producer" in result.stdout or "networks.kafka.uart_producer" in result.stdout:
            print("  ✓ UART Producer 프로세스 실행 중")
            for line in result.stdout.splitlines():
                if "uart_producer" in line:
                    print(f"    {line.strip()}")
            return True
        else:
            print("  ⚠ UART Producer 프로세스를 찾을 수 없습니다")
            print("     - display-switcher가 --enable-uart-producer로 실행되었는지 확인")
            return False
            
    except Exception as e:
        print(f"  ✗ 프로세스 확인 실패: {e}")
        return False


def main():
    print("\n" + "="*60)
    print("센서 데이터 흐름 디버깅")
    print("="*60)
    print("\n이 스크립트는 다음을 확인합니다:")
    print("  1. UART에서 직접 데이터 수신")
    print("  2. Kafka 연결")
    print("  3. Kafka 토픽에서 데이터 수신")
    print("  4. Sensor Display 데이터 파싱")
    print("  5. UART Producer 프로세스 실행 여부")
    
    results = []
    
    # 각 테스트 실행
    results.append(("UART 수신", check_uart_receiver()))
    results.append(("Kafka 연결", check_kafka_connection()))
    results.append(("Kafka 토픽 데이터", check_kafka_topic_data()))
    results.append(("데이터 파싱", check_sensor_display_parsing()))
    results.append(("UART Producer", check_uart_producer_running()))
    
    # 결과 요약
    print("\n" + "="*60)
    print("결과 요약")
    print("="*60)
    
    for name, result in results:
        status = "✓ 통과" if result else "✗ 실패"
        print(f"  {name}: {status}")
    
    all_passed = all(result for _, result in results)
    
    if all_passed:
        print("\n✓ 모든 테스트 통과!")
    else:
        print("\n⚠ 일부 테스트 실패")
        print("\n추가 확인 사항:")
        print("  1. launcher.py 실행 시 display-switcher가 --enable-uart-producer로 실행되는지 확인")
        print("  2. Kafka 브로커가 실행 중인지 확인: sudo systemctl status kafka")
        print("  3. UART 권한 확인: sudo usermod -aG dialout $USER")
        print("  4. 환경 변수 확인: KAFKA_BOOTSTRAP_SERVERS, KAFKA_SENSOR_TOPIC")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())

