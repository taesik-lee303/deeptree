#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MP4 Player Usage Examples
카프카 기반 MP4 플레이어 사용 예제
"""

import os
import sys
import time
import logging
from pathlib import Path

# 상위 모듈 경로 추가
sys.path.append(os.path.join(os.path.dirname(__file__), '../..'))

from modules.display.display_for_carecall.mp4_player import MP4Player, PlayerConfig, VideoConfig


def setup_logging(level="INFO"):
    """로깅 설정"""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("mp4_player.log", encoding='utf-8')
        ]
    )


def create_sample_videos_directory():
    """샘플 비디오 디렉토리 생성"""
    video_dir = Path("./videos")
    video_dir.mkdir(exist_ok=True)

    # 샘플 비디오 파일 정보 생성
    sample_videos = {
        "happy.mp4": "기쁜 감정용 비디오",
        "sad.mp4": "슬픈 감정용 비디오",
        "angry.mp4": "화난 감정용 비디오",
        "neutral.mp4": "중성 감정용 비디오",
        "default.mp4": "기본 비디오"
    }

    readme_content = "# 비디오 파일 디렉토리\n\n"
    readme_content += "이 디렉토리에 다음 비디오 파일들을 배치하세요:\n\n"

    for filename, description in sample_videos.items():
        readme_content += f"- `{filename}`: {description}\n"

    with open(video_dir / "README.md", "w", encoding="utf-8") as f:
        f.write(readme_content)

    print(f"Sample video directory created at: {video_dir.absolute()}")
    return str(video_dir)


def example_basic_usage():
    """기본 사용법 예제"""
    print("\n=== 기본 사용법 예제 ===")

    # 비디오 디렉토리 생성
    video_dir = create_sample_videos_directory()

    # 플레이어 설정
    config = PlayerConfig(
        bootstrap_servers="localhost:9092",
        topic="carecall.emotion",
        video_directory=video_dir,
        group_id="example-player",
        volume=0.8,
        fullscreen=False  # 데모용으로 창 모드
    )

    # 플레이어 생성
    player = MP4Player(config)

    # 커스텀 이벤트 핸들러 추가
    def emotion_event_handler(data):
        emotion = data.get("emotion", "unknown")
        timestamp = data.get("timestamp", "")
        print(f"[EVENT] Emotion detected: {emotion} at {timestamp}")

    player.add_event_handler(emotion_event_handler)

    try:
        # 플레이어 시작
        print(f"Starting MP4 player with topic: {config.topic}")
        player.start()

        print("Player started successfully!")
        print("Status:", player.get_status())
        print("Send emotion events to Kafka topic to trigger video playback...")
        print("Press Ctrl+C to stop")

        # 메인 루프
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nStopping player...")
    finally:
        player.stop()


def example_custom_video_configs():
    """커스텀 비디오 설정 예제"""
    print("\n=== 커스텀 비디오 설정 예제 ===")

    video_dir = create_sample_videos_directory()

    config = PlayerConfig(
        bootstrap_servers="localhost:9092",
        topic="carecall.emotion",
        video_directory=video_dir,
        group_id="custom-player"
    )

    player = MP4Player(config)

    # 커스텀 비디오 설정 추가
    custom_configs = {
        "excitement": VideoConfig(
            file_path=os.path.join(video_dir, "excitement.mp4"),
            trigger_conditions={"emotion": "happy", "intensity": "high"},
            priority=5,  # 높은 우선순위
            volume=1.0
        ),
        "calm": VideoConfig(
            file_path=os.path.join(video_dir, "calm.mp4"),
            trigger_conditions={"emotion": "neutral", "context": "meditation"},
            priority=3,
            loop=True  # 반복 재생
        ),
        "alarm": VideoConfig(
            file_path=os.path.join(video_dir, "alarm.mp4"),
            trigger_conditions={"alert_level": "high"},
            priority=10,  # 최고 우선순위
            volume=1.0
        )
    }

    # 설정 추가
    for name, video_config in custom_configs.items():
        player.add_video_config(name, video_config)

    # 이벤트 핸들러
    def detailed_event_handler(data):
        print(f"[CUSTOM] Received data: {data}")
        if "alert_level" in data:
            print(f"[ALERT] Alert level: {data['alert_level']}")

    player.add_event_handler(detailed_event_handler)

    try:
        player.start()
        print("Custom player configuration loaded!")
        print("Loaded video configs:")
        for name in player.video_configs.keys():
            print(f"  - {name}")

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nStopping custom player...")
    finally:
        player.stop()


def example_kafka_producer_simulator():
    """카프카 프로듀서 시뮬레이터 (테스트용)"""
    print("\n=== 카프카 프로듀서 시뮬레이터 ===")

    try:
        from kafka import KafkaProducer
        import json

        producer = KafkaProducer(
            bootstrap_servers="localhost:9092",
            value_serializer=lambda x: json.dumps(x, ensure_ascii=False).encode('utf-8')
        )

        # 샘플 이벤트들
        sample_events = [
            {"emotion": "happy", "timestamp": time.time(), "confidence": 0.85},
            {"emotion": "sad", "timestamp": time.time(), "confidence": 0.92},
            {"emotion": "angry", "timestamp": time.time(), "confidence": 0.78},
            {"emotion": "neutral", "timestamp": time.time(), "confidence": 0.65},
            {"emotion": "happy", "intensity": "high", "timestamp": time.time()},
            {"alert_level": "high", "message": "Emergency detected", "timestamp": time.time()}
        ]

        topic = "carecall.emotion"
        print(f"Sending sample events to topic: {topic}")

        for i, event in enumerate(sample_events, 1):
            print(f"Sending event {i}/{len(sample_events)}: {event}")
            producer.send(topic, event)
            time.sleep(2)  # 2초 간격

        producer.flush()
        producer.close()
        print("All events sent successfully!")

    except ImportError:
        print("kafka-python library not available for simulator")
    except Exception as e:
        print(f"Error in simulator: {e}")


def example_monitoring_player():
    """모니터링 기능이 포함된 플레이어 예제"""
    print("\n=== 모니터링 플레이어 예제 ===")

    video_dir = create_sample_videos_directory()

    config = PlayerConfig(
        bootstrap_servers="localhost:9092",
        topic="carecall.emotion",
        video_directory=video_dir,
        group_id="monitoring-player",
        debounce_ms=500  # 빠른 응답
    )

    player = MP4Player(config)

    # 통계 추적
    stats = {
        "events_received": 0,
        "videos_played": 0,
        "emotions_count": {},
        "start_time": time.time()
    }

    def monitoring_handler(data):
        stats["events_received"] += 1
        emotion = data.get("emotion")
        if emotion:
            stats["emotions_count"][emotion] = stats["emotions_count"].get(emotion, 0) + 1

        if player.state.value == "playing":
            stats["videos_played"] += 1

        # 10초마다 통계 출력
        if stats["events_received"] % 10 == 0:
            uptime = int(time.time() - stats["start_time"])
            print(f"\n--- Statistics (Uptime: {uptime}s) ---")
            print(f"Events received: {stats['events_received']}")
            print(f"Videos played: {stats['videos_played']}")
            print(f"Emotions: {stats['emotions_count']}")
            print(f"Current state: {player.state.value}")

    player.add_event_handler(monitoring_handler)

    try:
        player.start()
        print("Monitoring player started!")
        print("Statistics will be displayed every 10 events...")

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nStopping monitoring player...")
        print("Final statistics:")
        uptime = int(time.time() - stats["start_time"])
        print(f"  Total uptime: {uptime} seconds")
        print(f"  Events received: {stats['events_received']}")
        print(f"  Videos played: {stats['videos_played']}")
        print(f"  Emotions tracked: {stats['emotions_count']}")
    finally:
        player.stop()


def main():
    """메인 함수 - 예제 선택"""
    print("MP4 Player Examples")
    print("==================")
    print("1. Basic Usage Example")
    print("2. Custom Video Configurations")
    print("3. Kafka Producer Simulator")
    print("4. Monitoring Player Example")
    print("5. Create Sample Videos Directory")

    try:
        choice = input("\nSelect example (1-5): ").strip()

        setup_logging("INFO")

        if choice == "1":
            example_basic_usage()
        elif choice == "2":
            example_custom_video_configs()
        elif choice == "3":
            example_kafka_producer_simulator()
        elif choice == "4":
            example_monitoring_player()
        elif choice == "5":
            create_sample_videos_directory()
            print("Sample videos directory created successfully!")
        else:
            print("Invalid choice. Please select 1-5.")

    except KeyboardInterrupt:
        print("\nExiting...")
    except Exception as e:
        print(f"Error: {e}")
        logging.exception("Unexpected error")


if __name__ == "__main__":
    main()