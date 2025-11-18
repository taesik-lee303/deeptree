#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
 Player Module for Kafka Event-Driven Video Playback
카프카 이벤트 기반 MP4 재생 모듈
"""

import os
import json
import time
import logging
import threading
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, field
from enum import Enum

from kafka import KafkaConsumer
from kafka.errors import KafkaError


class PlayerState(Enum):
    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class VideoConfig:
    """비디오 파일 설정"""
    file_path: str
    trigger_conditions: Dict[str, Any] = field(default_factory=dict)
    priority: int = 0  # 높은 숫자가 우선순위
    loop: bool = False
    volume: float = 1.0


@dataclass
class PlayerConfig:
    """MP4 플레이어 설정"""
    # Kafka 설정
    bootstrap_servers: str = "localhost:9092"
    topic: str = "carecall.emotion"
    group_id: str = "mp4-player-consumer"

    # 비디오 설정
    video_directory: str = "./videos"
    default_video: Optional[str] = None

    # 플레이어 설정
    player_command: str = "ffplay"  # ffplay, vlc, mplayer 등
    fullscreen: bool = True
    auto_exit: bool = True
    volume: float = 0.8

    # 동작 설정
    debounce_ms: int = 1000  # 같은 이벤트 중복 방지
    max_retries: int = 3


class MP4Player:
    """카프카 이벤트 기반 MP4 플레이어"""

    def __init__(self, config: PlayerConfig):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)

        # 상태 관리
        self.state = PlayerState.IDLE
        self.current_process: Optional[subprocess.Popen] = None
        self.current_video: Optional[str] = None
        self.last_event_time: float = 0
        self.last_event_data: Optional[Dict] = None

        # 비디오 설정 매핑
        self.video_configs: Dict[str, VideoConfig] = {}
        self._load_video_configs()

        # Kafka 소비자
        self.consumer: Optional[KafkaConsumer] = None
        self.consumer_thread: Optional[threading.Thread] = None
        self.running = False

        # 이벤트 핸들러
        self.event_handlers: List[Callable[[Dict], None]] = []

    def _load_video_configs(self):
        """비디오 설정 로드"""
        video_dir = Path(self.config.video_directory)
        if not video_dir.exists():
            self.logger.warning(f"Video directory not found: {video_dir}")
            return

        # 기본 비디오 파일 매핑
        emotion_videos = {
            "happy": VideoConfig(
                file_path=str(video_dir / "happy.MOV"),
                trigger_conditions={"emotion": "happy"},
                priority=1,
                loop=True,
            ),
            "sad": VideoConfig(
                file_path=str(video_dir / "sad.MOV"),
                trigger_conditions={"emotion": "sad"},
                priority=1,
                loop=True,
            ),
            "angry": VideoConfig(
                file_path=str(video_dir / "angry.MOV"),
                trigger_conditions={"emotion": "angry"},
                priority=1,
                loop=True,
            ),
            "neutral": VideoConfig(
                file_path=str(video_dir / "neutral.mp4"),
                trigger_conditions={"emotion": "neutral"},
                priority=0,
                loop=True,
            ),
            "default": VideoConfig(
                file_path=self.config.default_video or str(video_dir / "default.MOV"),
                trigger_conditions={},
                priority=-1,
                loop=True,
            )
        }

        # 존재하는 파일만 설정에 추가
        for name, config in emotion_videos.items():
            if Path(config.file_path).exists():
                self.video_configs[name] = config
                self.logger.info(f"Loaded video config: {name} -> {config.file_path}")
            else:
                self.logger.warning(f"Video file not found: {config.file_path}")

    def add_video_config(self, name: str, config: VideoConfig):
        """비디오 설정 추가"""
        if Path(config.file_path).exists():
            self.video_configs[name] = config
            self.logger.info(f"Added video config: {name} -> {config.file_path}")
        else:
            self.logger.warning(f"Video file not found: {config.file_path}")

    def start(self):
        """플레이어 시작"""
        if self.running:
            self.logger.warning("Player already running")
            return

        try:
            # Kafka 소비자 초기화
            self.consumer = KafkaConsumer(
                self.config.topic,
                bootstrap_servers=self.config.bootstrap_servers,
                group_id=self.config.group_id,
                auto_offset_reset="latest",
                enable_auto_commit=True,
                value_deserializer=lambda m: json.loads(m.decode('utf-8'))
            )

            self.running = True

            # 소비자 스레드 시작
            self.consumer_thread = threading.Thread(
                target=self._consume_messages,
                daemon=True
            )
            self.consumer_thread.start()

            self.logger.info(f"MP4 Player started, listening on topic: {self.config.topic}")

        except Exception as e:
            self.logger.error(f"Failed to start player: {e}")
            self.stop()
            raise

    def stop(self):
        """플레이어 중지"""
        self.logger.info("Stopping MP4 Player...")

        self.running = False

        # 현재 재생 중인 비디오 중지
        self._stop_current_video()

        # 소비자 정리
        if self.consumer:
            try:
                self.consumer.close()
            except Exception as e:
                self.logger.error(f"Error closing consumer: {e}")
            self.consumer = None

        # 스레드 정리
        if self.consumer_thread and self.consumer_thread.is_alive():
            self.consumer_thread.join(timeout=5.0)

        self.state = PlayerState.IDLE
        self.logger.info("MP4 Player stopped")

    def _consume_messages(self):
        """카프카 메시지 소비"""
        while self.running:
            try:
                message_batch = self.consumer.poll(timeout_ms=1000)

                for topic_partition, messages in message_batch.items():
                    for message in messages:
                        if not self.running:
                            break

                        try:
                            self._process_message(message.value)
                        except Exception as e:
                            self.logger.error(f"Error processing message: {e}")

            except Exception as e:
                self.logger.error(f"Consumer error: {e}")
                if self.running:
                    time.sleep(1)  # 에러 시 잠시 대기

    def _process_message(self, data: Dict[str, Any]):
        """메시지 처리"""
        current_time = time.time()

        # 중복 이벤트 필터링
        if (current_time - self.last_event_time < self.config.debounce_ms / 1000.0 and
            self.last_event_data == data):
            return

        self.last_event_time = current_time
        self.last_event_data = data.copy()

        self.logger.debug(f"Processing message: {data}")

        if data.get("end"):
            self.logger.info("Received conversation end event; stopping playback")
            self.last_event_time = 0
            self.last_event_data = None
            self._stop_current_video()
            self.state = PlayerState.IDLE
            return

        # 이벤트 핸들러 호출
        for handler in self.event_handlers:
            try:
                handler(data)
            except Exception as e:
                self.logger.error(f"Event handler error: {e}")

        # 비디오 선택 및 재생
        video_config = self._select_video(data)
        if video_config:
            self._play_video(video_config)

    def _select_video(self, data: Dict[str, Any]) -> Optional[VideoConfig]:
        """데이터에 따른 비디오 선택"""
        matched_videos = []

        for name, config in self.video_configs.items():
            if self._matches_conditions(data, config.trigger_conditions):
                matched_videos.append((config.priority, name, config))

        if matched_videos:
            # 우선순위 순으로 정렬
            matched_videos.sort(key=lambda x: x[0], reverse=True)
            selected_config = matched_videos[0][2]
            self.logger.info(f"Selected video: {matched_videos[0][1]}")
            return selected_config

        # 기본 비디오
        if "default" in self.video_configs:
            self.logger.info("Using default video")
            return self.video_configs["default"]

        return None

    def _matches_conditions(self, data: Dict[str, Any], conditions: Dict[str, Any]) -> bool:
        """조건 매칭 확인"""
        if not conditions:
            return True

        for key, expected_value in conditions.items():
            if key not in data:
                return False

            actual_value = data[key]

            # 정확히 일치
            if actual_value == expected_value:
                continue

            # 리스트인 경우 포함 확인
            if isinstance(expected_value, list):
                if actual_value in expected_value:
                    continue

            # 조건 불만족
            return False

        return True

    def _play_video(self, config: VideoConfig):
        """비디오 재생"""
        if not Path(config.file_path).exists():
            self.logger.error(f"Video file not found: {config.file_path}")
            return

        if (
            self.current_process
            and self.current_video == config.file_path
            and self.state == PlayerState.PLAYING
        ):
            self.logger.debug("Requested video already playing; keep looping")
            return

        # 현재 재생 중인 비디오 중지
        self._stop_current_video()

        try:
            # 플레이어 명령어 구성
            cmd = self._build_player_command(config)

            self.logger.info(f"Playing video: {config.file_path}")

            # 비디오 재생
            self.current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            self.current_video = config.file_path
            self.state = PlayerState.PLAYING

            # 재생 완료 모니터링
            threading.Thread(
                target=self._monitor_playback,
                args=(self.current_process,),
                daemon=True
            ).start()

        except Exception as e:
            self.logger.error(f"Failed to play video: {e}")
            self.state = PlayerState.ERROR

    def _build_player_command(self, config: VideoConfig) -> List[str]:
        """플레이어 명령어 구성"""
        cmd = [self.config.player_command]

        # ffplay 옵션
        if self.config.player_command == "ffplay":
            cmd.extend(["-hide_banner", "-loglevel", "quiet"])

            # 2.1인치 원형 디스플레이에 맞게 크기 조정 (240x240)
            cmd.extend(["-x", "240", "-y", "240"])

            if self.config.fullscreen:
                cmd.append("-fs")

            if self.config.auto_exit:
                cmd.append("-autoexit")

            cmd.extend(["-volume", str(int(config.volume * 100))])

            if config.loop:
                cmd.extend(["-loop", "0"])

        # VLC 옵션
        elif self.config.player_command == "vlc":
            cmd.extend(["--intf", "dummy", "--play-and-exit"])

            if self.config.fullscreen:
                cmd.append("--fullscreen")

        cmd.append(config.file_path)
        return cmd

    def _monitor_playback(self, process: subprocess.Popen):
        """재생 모니터링"""
        try:
            process.wait()
            if process == self.current_process:
                self.current_process = None
                self.current_video = None
                self.state = PlayerState.IDLE
                self.logger.info("Video playback finished")
        except Exception as e:
            self.logger.error(f"Playback monitoring error: {e}")

    def _stop_current_video(self):
        """현재 비디오 중지"""
        if self.current_process:
            try:
                self.current_process.terminate()
                self.current_process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                self.current_process.kill()
            except Exception as e:
                self.logger.error(f"Error stopping video: {e}")
            finally:
                self.current_process = None
                self.current_video = None
                self.state = PlayerState.STOPPED

    def add_event_handler(self, handler: Callable[[Dict], None]):
        """이벤트 핸들러 추가"""
        self.event_handlers.append(handler)

    def get_status(self) -> Dict[str, Any]:
        """플레이어 상태 반환"""
        return {
            "state": self.state.value,
            "current_video": self.current_video,
            "video_configs": len(self.video_configs),
            "running": self.running
        }


def create_default_config(
    kafka_servers: str = "localhost:9092",
    topic: str = "carecall.emotion",
    video_dir: str = "./videos"
) -> PlayerConfig:
    """기본 설정 생성"""
    return PlayerConfig(
        bootstrap_servers=kafka_servers,
        topic=topic,
        video_directory=video_dir,
        group_id="mp4-player-consumer"
    )


# 테스트 및 데모용 메인 함수
def main():
    """데모 실행"""
    import argparse

    parser = argparse.ArgumentParser(description="Kafka-driven MP4 Player")
    parser.add_argument("--kafka", default="localhost:9092", help="Kafka bootstrap servers")
    parser.add_argument("--topic", default="carecall.emotion", help="Kafka topic to consume")
    parser.add_argument("--videos", default="./videos", help="Video directory")
    parser.add_argument("--log-level", default="INFO", help="Log level")

    args = parser.parse_args()

    # 로깅 설정
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # 플레이어 설정 및 시작
    config = create_default_config(
        kafka_servers=args.kafka,
        topic=args.topic,
        video_dir=args.videos
    )

    player = MP4Player(config)

    try:
        player.start()

        # 이벤트 핸들러 예제
        def log_event(data):
            print(f"Received event: {data}")

        player.add_event_handler(log_event)

        print(f"MP4 Player running. Status: {player.get_status()}")
        print("Press Ctrl+C to stop...")

        # 메인 스레드 대기
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nStopping player...")
    finally:
        player.stop()


if __name__ == "__main__":
    main()
