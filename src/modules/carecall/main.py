#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py
DeepCare Conversation System - 메인 진입점
통합 대화 시스템 실행 및 라우팅
"""

import os
import sys
import time
import argparse
import signal
import threading
import queue
import unicodedata
from typing import Optional, Set

# 현재 디렉토리를 Python 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.carecall.config import get_config, create_sample_config
from modules.carecall.activation import ActivationEvent, SensorTriggerWatcher
from modules.carecall.stt_tts.utils import setup_logging, get_logger, test_system, AudioUtils
from modules.carecall.stt_tts.stt import create_stt_manager
from modules.carecall.stt_tts.tts import create_tts_manager
from modules.carecall.stt_tts.utils import ConversationManager, AIServerClient

class DeepCareSystem:
    """DeepCare 통합 시스템"""
    
    def __init__(self, config_file: Optional[str] = None):
        # 설정 로드
        if config_file:
            os.environ['DEEPCARE_CONFIG'] = config_file

        self.config = get_config()
        self.activation_cfg = self.config.activation

        # 로깅 설정
        setup_logging(level="INFO")
        self.logger = get_logger(self.__class__.__name__)

        # 컴포넌트들
        self.stt_manager = None
        self.tts_manager = None
        self.ai_client = None
        self.conversation_manager = None

        # 상태
        self.is_running = False
        self.shutdown_event = threading.Event()
        self._last_activation_event: ActivationEvent | None = None
        self._wake_phrases_norm: Set[str] = {
            self._normalize_text(p)
            for p in (self.activation_cfg.wake_phrases or [])
            if self._normalize_text(p)
        }
        self._last_voice_trigger_ts: float = 0.0

        # 신호 핸들러 설정
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.logger.info("DeepCare System initialized")
    
    def _signal_handler(self, signum, frame):
        """시그널 핸들러 (Ctrl+C 등)"""
        self.logger.info(f"Received signal {signum}, shutting down...")
        self.shutdown()
    
    def initialize_components(self):
        """컴포넌트 초기화"""
        try:
            # STT 매니저 초기화
            self.logger.info("Initializing STT manager...")
            self.stt_manager = create_stt_manager()
            
            # TTS 매니저 초기화  
            self.logger.info("Initializing TTS manager...")
            self.tts_manager = create_tts_manager()
            
            # AI 서버 클라이언트 초기화
            if self.config.server.base_url:
                self.logger.info("Initializing AI server client...")
                self.ai_client = AIServerClient(self.config.server)
            
            # 대화 매니저 초기화
            self.conversation_manager = ConversationManager(
                self.stt_manager,
                self.tts_manager,
                self.ai_client
            )
            
            self.logger.info("All components initialized successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize components: {e}")
            return False
    
    def run_interactive_mode(self):
        """대화형 모드 실행"""
        self.logger.info("Starting interactive conversation mode...")

        try:
            if not self.wait_for_activation():
                self.logger.info("Activation wait aborted")
                return

            self.is_running = True
            self.conversation_manager.start_conversation()

            # 메인 루프
            while self.is_running and not self.shutdown_event.is_set():
                time.sleep(0.1)

        except KeyboardInterrupt:
            self.logger.info("Interactive mode interrupted by user")
        except Exception as e:
            self.logger.error(f"Interactive mode error: {e}")
        finally:
            self.conversation_manager.stop_conversation()

    def wait_for_activation(self) -> bool:
        """센서/호출어 기반으로 케어콜 시작 조건을 대기."""
        # 활성화 조건이 비어 있다면 바로 통과
        if self.activation_cfg.noise_threshold <= 0 and not self._wake_phrases_norm:
            self.logger.info("Activation gating disabled; starting immediately")
            return True

        activation_queue: queue.Queue[ActivationEvent] = queue.Queue(maxsize=1)

        def _push_event(event: ActivationEvent) -> None:
            try:
                activation_queue.put_nowait(event)
            except queue.Full:
                pass

        watcher = SensorTriggerWatcher(self.activation_cfg, _push_event)
        watcher_active = watcher.start()

        voice_enabled = bool(self._wake_phrases_norm)
        stt_started = False

        if voice_enabled and self.stt_manager:
            def _on_transcribed(text: str) -> None:
                normalized = self._normalize_text(text)
                if not normalized:
                    return
                if self._is_wake_phrase(normalized):
                    now = time.time()
                    if self.activation_cfg.sensor_timeout_sec > 0 and (now - self._last_voice_trigger_ts) < self.activation_cfg.sensor_timeout_sec:
                        return
                    self._last_voice_trigger_ts = now
                    self.logger.info("Wake phrase detected: %s", text)
                    _push_event(ActivationEvent(source="voice", payload={"text": text}))

            try:
                self.stt_manager.start(on_transcribed=_on_transcribed)
                stt_started = True
                self.logger.info(
                    "Waiting for wake phrases: %s",
                    ", ".join(sorted(self.activation_cfg.wake_phrases or [])) or "(none)"
                )
            except Exception as exc:
                voice_enabled = False
                self.logger.error("Failed to start STT for wake phrase detection: %s", exc)

        if not watcher_active:
            self.logger.warning("Sensor trigger watcher inactive; relying on voice wake-up only")
        else:
            self.logger.info(
                "Sensor trigger armed (noise ≥ %s, motion window %ss)",
                self.activation_cfg.noise_threshold,
                self.activation_cfg.motion_window_sec,
            )

        if not watcher_active and not voice_enabled:
            self.logger.warning("No activation mechanism available; starting immediately")
            return True

        triggered: ActivationEvent | None = None

        try:
            while not self.shutdown_event.is_set():
                try:
                    triggered = activation_queue.get(timeout=0.5)
                    break
                except queue.Empty:
                    continue
        finally:
            if watcher_active:
                watcher.stop()
            if stt_started:
                self.stt_manager.stop()

        if triggered is None:
            return False

        self._last_activation_event = triggered
        self.logger.info("Activation satisfied by %s", triggered.source)
        return True

    def _normalize_text(self, text: str) -> str:
        s = unicodedata.normalize("NFKC", (text or "")).lower()
        return "".join(
            ch for ch in s if unicodedata.category(ch)[0] not in {"Z", "P"}
        )

    def _is_wake_phrase(self, normalized: str) -> bool:
        if not normalized:
            return False
        if normalized in self._wake_phrases_norm:
            return True
        # 부분 포함(호출어가 긴 문장 속에 포함된 경우) 체크
        return any(phrase in normalized for phrase in self._wake_phrases_norm)

    def run_stt_only(self):
        """STT만 실행"""
        self.logger.info("Starting STT-only mode...")

        def on_transcribed(text):
            print(f"[STT] {text}")
        
        try:
            self.stt_manager.start(on_transcribed)
            
            while not self.shutdown_event.is_set():
                time.sleep(0.1)
                
        except KeyboardInterrupt:
            self.logger.info("STT mode interrupted")
        finally:
            self.stt_manager.stop()
    
    
    def run_test_mode(self):
        """테스트 모드 실행"""
        self.logger.info("Running system tests...")
        
        # 시스템 정보 출력
        test_system()
        
        # STT 테스트
        if self.stt_manager:
            print("\n=== STT Test ===")
            test_text = "안녕하세요 테스트입니다"
            print(f"Test would transcribe: {test_text}")
        
        # TTS 테스트
        if self.tts_manager:
            print("\n=== TTS Test ===")
            test_texts = [
                "안녕하세요. TTS 테스트입니다.",
                "음성 합성이 정상적으로 작동하고 있습니다."
            ]
            
            for text in test_texts:
                print(f"Speaking: {text}")
                try:
                    result = self.tts_manager.speak(text)
                    print(f"Result: {'Success' if result else 'Failed'}")
                except Exception as e:
                    print(f"Error: {e}")
                time.sleep(1)
        
        # AI 클라이언트 테스트
        if self.ai_client:
            print("\n=== AI Client Test ===")
            test_queries = ["안녕하세요", "오늘 날씨가 어때요?", "이름이 뭐예요?"]
            
            for query in test_queries:
                print(f"Query: {query}")
                response = self.ai_client.send_chat_request(query)
                if response.success:
                    print(f"Response: {response.ai_response}")
                    print(f"Time: {response.response_time:.2f}s")
                else:
                    print(f"Error: {response.error_message}")
                print()
        
        print("=== Test Complete ===")
    
    def shutdown(self):
        """시스템 종료"""
        self.logger.info("Shutting down system...")
        self.is_running = False
        self.shutdown_event.set()
        
        # 컴포넌트들 정리
        if self.conversation_manager:
            self.conversation_manager.stop_conversation()
        
        if self.stt_manager:
            self.stt_manager.stop()
        
        if self.tts_manager:
            self.tts_manager.close()
        
        if self.ai_client:
            self.ai_client.close()
        
        self.logger.info("System shutdown complete")

def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(
        description='DeepCare Conversation System',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
실행 모드:
  interactive  - 대화형 모드 (기본)
  stt-only     - STT만 실행
  test         - 시스템 테스트

예시:
  python main.py                          # 대화형 모드
  python main.py --mode stt-only          # STT만 실행
  python main.py --mode test              # 테스트 모드
        """
    )
    
    # 실행 모드
    parser.add_argument('--mode', choices=['interactive', 'stt-only', 'test'],
                       default='interactive', help='실행 모드')
    
    
    # 설정 파일
    parser.add_argument('--config', type=str,
                       help='설정 파일 경로')
    
    # 유틸리티 기능들
    parser.add_argument('--list-devices', action='store_true',
                       help='오디오 디바이스 목록')
    parser.add_argument('--test-device', type=int,
                       help='오디오 디바이스 테스트')
    parser.add_argument('--create-config', action='store_true',
                       help='샘플 설정 파일 생성')
    parser.add_argument('--system-info', action='store_true',
                       help='시스템 정보 출력')
    
    args = parser.parse_args()
    
    # 유틸리티 기능들 처리
    if args.create_config:
        create_sample_config()
        return
    
    if args.system_info:
        test_system()
        return
    
    if args.list_devices:
        print("오디오 디바이스 목록:")
        devices = AudioUtils.list_audio_devices()
        
        print("\n입력 디바이스:")
        for device in devices['input']:
            print(f"  [{device['index']}] {device['name']} "
                  f"({device['channels']}ch, {device['sample_rate']}Hz)")
        
        print("\n출력 디바이스:")
        for device in devices['output']:
            print(f"  [{device['index']}] {device['name']}")
        
        print(f"\n기본값: 입력={devices['default_input']}, 출력={devices['default_output']}")
        return
    
    if args.test_device is not None:
        print(f"디바이스 {args.test_device} 테스트 중...")
        result = AudioUtils.test_audio_device(args.test_device)
        if result['success']:
            print(f"테스트 성공!")
            print(f"  오디오 레벨: {result['audio_level']:.2f}")
            print(f"  신호 감지: {'Yes' if result['has_signal'] else 'No'}")
        else:
            print(f"테스트 실패: {result['error']}")
        return
    
    # 시스템 초기화 및 실행
    try:
        system = DeepCareSystem(args.config)
        
        # 컴포넌트 초기화
        if not system.initialize_components():
            print("컴포넌트 초기화 실패")
            sys.exit(1)
        
        # 모드별 실행
        if args.mode == 'interactive':
            print("=== 대화형 모드 시작 ===")
            wake_info = ", ".join(system.activation_cfg.wake_phrases or []) or "(호출어 미설정)"
            print(
                "소음 ≥ {threshold} & PIR 감지 또는 호출어 [{phrases}] 인식 시 케어콜이 시작됩니다.\n'Ctrl+C'로 종료할 수 있습니다.".format(
                    threshold=system.activation_cfg.noise_threshold,
                    phrases=wake_info,
                )
            )
            system.run_interactive_mode()
            
        elif args.mode == 'stt-only':
            print("=== STT 모드 시작 ===")
            print("음성 인식 중... 'Ctrl+C'로 종료")
            system.run_stt_only()
            
        elif args.mode == 'test':
            system.run_test_mode()
        
    except KeyboardInterrupt:
        print("\n사용자에 의해 중단됨")
    except Exception as e:
        print(f"오류 발생: {e}")
        sys.exit(1)
    finally:
        try:
            system.shutdown()
        except:
            pass

if __name__ == "__main__":
    main()
