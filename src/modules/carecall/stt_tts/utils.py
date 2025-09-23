#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
utils.py
공통 유틸리티 및 도우미 함수들
"""

import os
import sys
import json
import time
import logging
import threading

import sounddevice as sd
from typing import Dict, Any, Optional, List, Callable, Union
from datetime import datetime
import numpy as np

# 상위 디렉토리에서 config import
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from config import get_config, ServerConfig

# AI 서버 관련
try:
    import requests
    from dataclasses import dataclass, asdict
    from enum import Enum
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# Silero VAD
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False


def setup_logging(level: str = "INFO", log_file: Optional[str] = None):
    """로깅 설정"""
    log_level = getattr(logging, level.upper(), logging.INFO)

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # 콘솔 핸들러
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    handlers = [console_handler]

    # 파일 핸들러 (선택적)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    logging.basicConfig(
        level=log_level,
        handlers=handlers,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # 외부 라이브러리 로그 레벨 조정
    logging.getLogger('urllib3').setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """로거 인스턴스 반환"""
    return logging.getLogger(name)


def now_timestamp() -> float:
    """현재 타임스탬프 반환"""
    return time.time()


def format_timestamp(timestamp: float, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """타임스탬프를 문자열로 포맷"""
    return datetime.fromtimestamp(timestamp).strftime(format_str)


def safe_json_loads(data: Union[str, bytes], default: Any = None) -> Any:
    """안전한 JSON 파싱"""
    try:
        if isinstance(data, bytes):
            data = data.decode('utf-8')
        return json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logging.getLogger(__name__).warning(f"JSON parse error: {e}")
        return default


def safe_json_dumps(obj: Any, default: Any = None, **kwargs) -> str:
    """안전한 JSON 직렬화"""
    try:
        return json.dumps(obj, ensure_ascii=False, **kwargs)
    except (TypeError, ValueError) as e:
        logging.getLogger(__name__).warning(f"JSON serialize error: {e}")
        return json.dumps(default or {}, ensure_ascii=False)


class AudioUtils:
    """오디오 관련 유틸리티"""

    @staticmethod
    def list_audio_devices():
        """사용 가능한 오디오 디바이스 목록"""
        try:
            devices = sd.query_devices()
            inputs = []
            outputs = []
            for i, d in enumerate(devices):
                item = {
                    'index': i,
                    'name': d.get('name'),
                    'max_input_channels': d.get('max_input_channels', 0),
                    'max_output_channels': d.get('max_output_channels', 0),
                    'default_samplerate': d.get('default_samplerate')
                }
                if item['max_input_channels'] > 0:
                    inputs.append(item)
                if item['max_output_channels'] > 0:
                    outputs.append(item)

            return {'input': inputs, 'output': outputs}

        except Exception as e:
            logging.getLogger(__name__).error(f"Failed to list audio devices: {e}")
            return {'input': [], 'output': []}

    @staticmethod
    def quick_record_check(device_index: int, duration: float = 1.0, samplerate: int = 16000):
        """해당 입력 장치가 실제로 신호를 내는지 짧게 체크"""
        try:
            recording = sd.rec(
                int(duration * samplerate),
                samplerate=samplerate,
                channels=1,
                device=device_index,
                dtype='int16'
            )
            sd.wait()

            audio_level = np.abs(recording).mean()
            return {
                'success': True,
                'device_index': device_index,
                'duration': duration,
                'audio_level': float(audio_level),
                'has_signal': audio_level > 100  # 임계값
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }


class SystemInfo:
    """시스템 정보 유틸리티"""

    @staticmethod
    def get_system_info() -> Dict[str, Any]:
        """시스템 정보 수집"""
        import platform
        import psutil

        try:
            return {
                'platform': platform.platform(),
                'python_version': platform.python_version(),
                'cpu_count': psutil.cpu_count(),
                'memory_total': psutil.virtual_memory().total,
                'memory_available': psutil.virtual_memory().available,
                'disk_usage': dict(psutil.disk_usage('/'))
            }
        except ImportError:
            return {
                'platform': platform.platform(),
                'python_version': platform.python_version()
            }

    @staticmethod
    def get_gpu_info() -> Dict[str, Any]:
        """GPU 정보 (있다면)"""
        gpu_info = {'available': False}

        if TORCH_AVAILABLE:
            try:
                gpu_info.update({
                    'available': torch.cuda.is_available(),
                    'device_count': torch.cuda.device_count() if torch.cuda.is_available() else 0,
                    'current_device': torch.cuda.current_device() if torch.cuda.is_available() else None
                })

                if torch.cuda.is_available():
                    gpu_info['devices'] = []
                    for i in range(torch.cuda.device_count()):
                        gpu_info['devices'].append({
                            'index': i,
                            'name': torch.cuda.get_device_name(i),
                            'memory_total': torch.cuda.get_device_properties(i).total_memory
                        })
            except Exception:
                pass

        return gpu_info


if REQUESTS_AVAILABLE:
    class RequestType(Enum):
        CHAT = "chat"
        QA = "question_answer"
        COMMAND = "command"

    @dataclass
    class SessionRequest:
        event_id: int = 1
        user_id: int = 1

    @dataclass
    class ChatRequest:
        session_id: int
        user_id: int
        content: str
        emotion: str = "neutral"

    @dataclass
    class LegacyChatRequest:
        user_text: str
        request_type: RequestType = RequestType.CHAT
        context: Optional[Dict[str, Any]] = None
        user_id: str = "raspberry_pi"
        timestamp: float = None

        def __post_init__(self):
            if self.timestamp is None:
                self.timestamp = time.time()

    @dataclass
    class SessionResponse:
        success: bool
        session_id: Optional[int] = None
        user_id: Optional[int] = None
        idx: Optional[int] = None
        role: Optional[str] = None
        content: Optional[str] = None
        emotion: Optional[str] = None
        end: bool = False
        id: Optional[int] = None
        created_at: Optional[str] = None
        updated_at: Optional[str] = None
        error_message: Optional[str] = None

    @dataclass
    class ChatResponse:
        success: bool
        session_id: Optional[int] = None
        user_id: Optional[int] = None
        idx: Optional[int] = None
        role: Optional[str] = None
        content: Optional[str] = None
        emotion: Optional[str] = None
        end: bool = False
        id: Optional[int] = None
        created_at: Optional[str] = None
        updated_at: Optional[str] = None
        error_message: Optional[str] = None
        response_time: float = 0.0

        @property
        def ai_response(self) -> Optional[str]:
            return self.content

    class AIServerClient:
        """AI 서버 클라이언트"""

        DUMMY_RESPONSES = {
            "오늘 날씨": "오늘은 맑고 화창한 날씨입니다.",
            "이름": "제 이름은 AI 비서입니다.",
            "안녕": "안녕하세요! 반갑습니다.",
            "기능": "저는 음성 인식, 대화, 정보 제공 등을 할 수 있습니다.",
            "시간": "시간 관련 질문을 해주시면 답변드리겠습니다.",
        }

        def __init__(self, config: ServerConfig = None):
            self.config = config or ServerConfig()
            self.session = requests.Session()
            self.logger = get_logger(self.__class__.__name__)
            self.current_session_id = None

            if self.config.api_key:
                self.session.headers.update({
                    'Authorization': f'Bearer {self.config.api_key}',
                    'Content-Type': 'application/json'
                })
            else:
                self.session.headers.update({'Content-Type': 'application/json'})

        def _get_dummy_response(self, text: str) -> str:
            text_lower = (text or "").lower()
            for keyword, response in self.DUMMY_RESPONSES.items():
                if keyword in text_lower:
                    return response
            return f"'{text}' 에 대한 답변입니다. (더미 모드)"

        def create_session(self) -> SessionResponse:
            start_time = time.time()

            if self.config.dummy_mode:
                time.sleep(0.3)
                self.current_session_id = 999
                return SessionResponse(
                    success=True,
                    session_id=999,
                    user_id=self.config.user_id,
                    idx=1,
                    role="assistant",
                    content="안녕하세요, 어르신! 오늘 기분은 어떠세요?",
                    emotion="happy",
                    id=999,
                    created_at=datetime.now().isoformat()
                )

            request = SessionRequest(event_id=self.config.event_id, user_id=self.config.user_id)

            for attempt in range(self.config.max_retries):
                try:
                    response = self.session.post(
                        f"{self.config.base_url}/chat/sessions",
                        json=asdict(request),
                        timeout=self.config.timeout
                    )
                    if response.status_code == 200:
                        data = response.json()
                        self.current_session_id = data.get('session_id')
                        return SessionResponse(
                            success=True,
                            session_id=data.get('session_id'),
                            user_id=data.get('user_id'),
                            idx=data.get('idx'),
                            role=data.get('role'),
                            content=data.get('content'),
                            emotion=data.get('emotion'),
                            end=data.get('end', False),
                            id=data.get('id'),
                            created_at=data.get('created_at'),
                            updated_at=data.get('updated_at')
                        )
                    else:
                        self.logger.warning(f"Session creation failed {response.status_code}: {response.text}")

                except requests.exceptions.Timeout:
                    self.logger.warning(f"Session creation timeout (attempt {attempt + 1})")
                except requests.exceptions.ConnectionError:
                    self.logger.warning(f"Session creation connection error (attempt {attempt + 1})")
                except Exception as e:
                    self.logger.error(f"Session creation error: {e}")

                if attempt < self.config.max_retries - 1:
                    time.sleep(self.config.retry_delay)

            return SessionResponse(success=False, error_message="세션 생성에 실패했습니다.")

        def send_chat_request(self, text: str, emotion: str = "neutral",
                              context: Optional[Dict] = None) -> 'ChatResponse':
            start_time = time.time()

            if not self.current_session_id:
                return ChatResponse(
                    success=False,
                    error_message="세션이 생성되지 않았습니다. create_session()을 먼저 호출하세요.",
                    response_time=time.time() - start_time
                )

            if self.config.dummy_mode:
                time.sleep(0.5)
                return ChatResponse(
                    success=True,
                    session_id=self.current_session_id,
                    user_id=self.config.user_id,
                    idx=2,
                    role="assistant",
                    content=self._get_dummy_response(text),
                    emotion="happy",
                    id=1000,
                    created_at=datetime.now().isoformat(),
                    response_time=time.time() - start_time
                )

            request = ChatRequest(
                session_id=self.current_session_id,
                user_id=self.config.user_id,
                content=text,
                emotion=emotion
            )

            for attempt in range(self.config.max_retries):
                try:
                    response = self.session.post(
                        f"{self.config.base_url}/chat/messages",
                        json=asdict(request),
                        timeout=self.config.timeout
                    )
                    if response.status_code == 200:
                        data = response.json()
                        return ChatResponse(
                            success=True,
                            session_id=data.get('session_id'),
                            user_id=data.get('user_id'),
                            idx=data.get('idx'),
                            role=data.get('role'),
                            content=data.get('content'),
                            emotion=data.get('emotion'),
                            end=data.get('end', False),
                            id=data.get('id'),
                            created_at=data.get('created_at'),
                            updated_at=data.get('updated_at'),
                            response_time=time.time() - start_time
                        )
                    else:
                        self.logger.warning(f"Server returned {response.status_code}: {response.text}")

                except requests.exceptions.Timeout:
                    self.logger.warning(f"Request timeout (attempt {attempt + 1})")
                except requests.exceptions.ConnectionError:
                    self.logger.warning(f"Connection error (attempt {attempt + 1})")
                except Exception as e:
                    self.logger.error(f"Request error: {e}")

                if attempt < self.config.max_retries - 1:
                    time.sleep(self.config.retry_delay)

            return ChatResponse(
                success=False,
                error_message="서버 통신에 실패했습니다.",
                response_time=time.time() - start_time
            )


class VADUtils:
    """VAD 관련 유틸리티"""

    @staticmethod
    def load_silero_vad():
        """Silero VAD 모델 로드"""
        if not TORCH_AVAILABLE:
            raise ImportError("torch not available for VAD")
        try:
            model, utils = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False
            )
            return model, utils
        except Exception as e:
            logging.getLogger(__name__).error(f"Failed to load Silero VAD: {e}")
            raise


class ConversationManager:
    """대화 관리자"""

    def __init__(self, stt_manager=None, tts_manager=None, ai_client=None):
        self.stt = stt_manager
        self.tts = tts_manager
        self.ai_client = ai_client

        self.state = "IDLE"  # IDLE, LISTENING, PROCESSING, SPEAKING
        self.conversation_history: List[Dict[str, Any]] = []
        self.local_command_handler = None
        self.bargein_guard_ms = int(os.getenv("BARGEIN_GUARD_MS", "800"))  # 1.4s 권장
        self.echo_drop_enabled = os.getenv("ECHO_DROP", "1") != "0"        # ECHO_DROP=0 이면 끔
        self._guard_until = 0.0
        self._last_ai_text = ""
        self._last_ai_time = 0.0

        if self.tts:
            # LocalCommandHandler는 tts.py 내에 정의
            from modules.carecall.stt_tts.tts import LocalCommandHandler
            self.local_command_handler = LocalCommandHandler(self.tts)

        self.logger = get_logger(self.__class__.__name__)

    def start_conversation(self):
        """대화 시작"""
        if not self.stt or not self.tts:
            raise ValueError("STT and TTS managers required")

        # AI 클라이언트 세션 생성
        if self.ai_client:
            session_response = self.ai_client.create_session()
            if session_response.success and session_response.content:
                greeting = session_response.content
                self.logger.info(f"Session created: {session_response.session_id}")
            else:
                greeting = "죄송합니다. 서버 연결에 문제가 있습니다."
                self.logger.error("Failed to create session")
        else:
            greeting = "안녕하세요. 무엇을 도와드릴까요?"

        def on_speech_recognized(text):
            self._handle_speech_input(text)

        self.state = "SPEAKING"
        self._pause_stt()
        self.tts.speak(greeting)
        self._resume_stt()
        self.logger.info(">>> 이제 말씀해주세요. 듣고 있습니다..    .")

        self.state = "LISTENING"
        self.stt.start(on_speech_recognized)

    def _handle_speech_input(self, text: str):
        # 1) 바지인 가드 (값이 0보다 클 때만)
        if self.bargein_guard_ms > 0 and time.monotonic() < self._guard_until:
            remain = int((self._guard_until - time.monotonic()) * 1000)
            self.logger.info(f"[DROP] guarded {remain}ms: {text}")
            return

        # ✨ 2) 에코 필터: 직전 AI 멘트와 유사하면 무시
        if self.echo_drop_enabled:
            try:
                if self._is_echo_of_last_ai(text):
                    self.logger.info(f"[DROP] echo-like STT: {text}")
                    return
            except Exception as e:
                self.logger.error(f"Echo filter error: %s", e)
        """음성 입력 처리 — 필러와 서버요청 병렬 모드"""
        if self.state != "LISTENING":
            return

        self.state = "PROCESSING"
        self.logger.info(f"Processing input: {text}")

        # 대화 기록
        self.conversation_history.append({
            'timestamp': time.time(),
            'type': 'user',
            'text': text
        })

        # 턴별 이벤트/스레드 초기화
        import threading
        self._ai_done = threading.Event()
        self._filler_done = threading.Event()
        self._filler_thread = None

        # 1) 로컬 명령어는 즉시 처리(필러 병렬과 무관)
        local_response = None
        if self.local_command_handler:
            try:
                local_response = self.local_command_handler.check_command(text)
            except Exception as e:
                self.logger.error(f"Local command error: {e}")

        if local_response:
            # 로컬 응답은 곧바로 말하고 종료/복귀
            self._speak_response(local_response)
            if self.local_command_handler.is_exit_command(text):
                self.stop_conversation()
                return
            self.state = "LISTENING"
            return

        # 2) AI 요청 스레드 — 응답 도착 시 필러가 돌고 있으면 잠깐만 기다렸다가 응답 말하기
        def process_ai_response():
            try:
                emotion = getattr(self, "_detect_emotion_from_text", lambda _: "neutral")(text)
                resp = self.ai_client.send_chat_request(text, emotion) if self.ai_client else None
                self._ai_done.set()

                # 필러와 겹치지 않게 최대 0.6초까지만 대기(필요 시 조절)
                if self._filler_done:
                    self._filler_done.wait(0.6)

                if resp and resp.success and resp.ai_response:
                    self._speak_response(resp.ai_response)
                    if getattr(resp, "end", False):
                        self.stop_conversation()
                        return
                else:
                    self._speak_response("죄송합니다. 답변을 생성할 수 없습니다.")
            except Exception as e:
                self.logger.exception("AI response error: %s", e)
                self._speak_response("죄송합니다. 서버와 통신이 원활하지 않아요.")
            finally:
                if self.state != "IDLE":
                    self.state = "LISTENING"

        threading.Thread(target=process_ai_response, daemon=True).start()

        # 3) 필러 TTS를 '병렬'로 시작 (초고속 응답이면 defer 동안 생략됨)
        self._start_filler_parallel(defer_ms=150)

    # --- 병렬 제어용 이벤트/스레드 핸들 (턴마다 새로 세팅) ---
    # self._ai_done, self._filler_done, self._filler_thread  는 _handle_speech_input 시작부에서 매 턴 초기화합니다.

    def _norm(self, s: str) -> str:
        import unicodedata
        s = (s or "")
        # 유니코드 정규화 + 소문자
        s = unicodedata.normalize("NFKC", s).lower()
        # 공백/문장부호 제거: 유니코드 범주로 필터
        out = []
        for ch in s:
            cat = unicodedata.category(ch)
            if not (cat.startswith("Z") or cat.startswith("P")):  # Z*: 구분자, P*: 문장부호
                out.append(ch)
        return "".join(out)


    def _is_echo_of_last_ai(self, text: str) -> bool:
        """직전 AI 멘트와 거의 동일/부분포함이면 되먹임(에코)으로 간주"""
        if not text or not self._last_ai_text:
            return False
        a = self._norm(text)
        b = self._norm(self._last_ai_text)
        if len(a) < 6 or len(b) < 6:
            return False
        # 부분포함(길이 충분) 체크
        if (a in b and len(a) / max(1, len(b)) >= 0.6) or (b in a and len(b) / max(1, len(a)) >= 0.6):
            return True
        # 유사도 체크
        try:
            from difflib import SequenceMatcher
            return SequenceMatcher(None, a, b).ratio() >= 0.85
        except Exception:
            return False
    

    def _start_filler_parallel(self, defer_ms: int = 150):
        """
        필러 TTS를 별도 스레드로 재생. 
        - defer_ms 동안 AI 응답이 먼저 오면 필러를 생략(초단기 응답일 때 불필요한 필러 제거)
        - 재생 중엔 STT 일시정지, 끝나면 120ms 후 재개
        """
        import threading, time

        if not getattr(self, "local_command_handler", None):
            return

        try:
            filler = self.local_command_handler.get_filler_phrase()
            if not filler:
                return
        except Exception:
            return

        evt_ai = self._ai_done
        evt_done = self._filler_done

        def _run_filler():
            try:
                time.sleep(defer_ms / 1000.0)
                # AI가 이미 끝났다면 필러 생략
                if evt_ai.is_set():
                    return
                self._pause_stt()
                self.tts.speak(filler)        # 블로킹 재생
                time.sleep(0.12)              # 잔향 방지용 아주 짧은 대기
            finally:
                self._resume_stt()
                evt_done.set()

        self._filler_thread = threading.Thread(target=_run_filler, daemon=True)
        self._filler_thread.start()
            

    def _speak_response(self, text: str):
        """응답 음성 출력(잔향 방지 + 바지인 가드 설정)"""
        self.state = "SPEAKING"

        self.conversation_history.append({
            'timestamp': time.time(),
            'type': 'assistant',
            'text': text
        })

        # STT 일시정지 → TTS → (짧은 잔향 대기) → STT 재개
        self._pause_stt()
        self.tts.speak(text)

        import time as _time
        time.sleep(0.20)  # 잔향 ~200ms
        self._resume_stt()

        # ✨ 바지인 가드 & 마지막 AI 멘트 기록
        self._last_ai_text = text or ""
        self._last_ai_time = _time.monotonic()
        if self.bargein_guard_ms > 0:
            self._guard_until = self._last_ai_time + (self.bargein_guard_ms / 1000.0)
        else:
            self._guard_until = 0.0

        self.logger.info(f"Response: {text}")
        self.state = "LISTENING"



    def _detect_emotion_from_text(self, text: str) -> str:
        """매우 단순한 규칙 기반 감정 태깅. 
        서버가 감정 파라미터를 받는 구조라면 최소한 'neutral'이라도 넘겨야 하므로 기본 제공."""
        if not text:
            return "neutral"
        t = text.lower()

        # 긍정
        if any(k in t for k in ["재밌", "좋아", "행복", "좋았습니다", "기분 좋아", "만족"]):
            return "happy"
        # 분노/짜증
        if any(k in t for k in ["화나", "짜증", "빡치", "열받", "화났"]):
            return "angry"
        # 슬픔/우울
        if any(k in t for k in ["슬퍼", "우울", "속상", "눈물"]):
            return "sad"
        # 불안/걱정
        if any(k in t for k in ["불안", "걱정", "긴장", "초조"]):
            return "anxious"

        return "neutral"

    # PATCH: STT 캡처 일시정지/재개를 공용 헬퍼로 제공
    def _pause_stt(self):
        try:
            if self.stt and getattr(self.stt, "audio_capture", None):
                self.stt.audio_capture.stop_capture()
        except Exception:
            pass

    def _resume_stt(self):
        try:
            if self.stt and getattr(self.stt, "audio_capture", None):
                self.stt.audio_capture.start_capture()
        except Exception:
            pass

    def stop_conversation(self):
        """대화 종료"""
        self.state = "IDLE"

        if self.stt:
            try:
                self.stt.stop()
            except Exception:
                pass

        if self.tts:
            try:
                self.tts.close()
            except Exception:
                pass

        if self.ai_client:
            try:
                self.ai_client.close()
            except Exception:
                pass

        self.logger.info("Conversation stopped")


class FileUtils:
    """파일 관련 유틸리티"""

    @staticmethod
    def ensure_directory(path: str):
        os.makedirs(path, exist_ok=True)

    @staticmethod
    def safe_filename(filename: str) -> str:
        import re
        safe = re.sub(r'[<>:"/\\|?*]', '_', filename)
        return safe[:255]

    @staticmethod
    def backup_file(file_path: str, backup_dir: str = None):
        if not os.path.exists(file_path):
            return None
        backup_dir = backup_dir or os.path.dirname(file_path)
        FileUtils.ensure_directory(backup_dir)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = os.path.basename(file_path)
        name, ext = os.path.splitext(base_name)
        backup_name = f"{name}_{timestamp}{ext}"
        backup_path = os.path.join(backup_dir, backup_name)
        import shutil
        shutil.copy2(file_path, backup_path)
        return backup_path


def test_system():
    """시스템 종합 테스트"""
    print("=== DeepCare Conversation System Test ===")

    # 시스템 정보
    print("\n1. System Information:")
    sys_info = SystemInfo.get_system_info()
    for key, value in sys_info.items():
        print(f"   {key}: {value}")

    # GPU 정보
    print("\n2. GPU Information:")
    gpu_info = SystemInfo.get_gpu_info()
    if gpu_info['available']:
        print(f"   GPU Available: {gpu_info['device_count']} devices")
        for device in gpu_info.get('devices', []):
            print(f"   - {device['name']} (Memory: {device['memory_total']} bytes)")
    else:
        print("   GPU: Not available")

    # 오디오 디바이스
    print("\n3. Audio Devices:")
    audio_devices = AudioUtils.list_audio_devices()
    print(f"   Input devices: {len(audio_devices['input'])}")
    for device in audio_devices['input'][:3]:
        print(f"   - [{device['index']}] {device['name']}")

    # 설정 테스트
    print("\n4. Configuration:")
    config = get_config()
    print(f"   Whisper model: {config.whisper.model}")
    print(f"   TTS engine: OpenAI TTS")
    print(f"   Audio sample rate: {config.audio.sample_rate}Hz")

    # AI 서버 테스트 (더미 모드)
    if REQUESTS_AVAILABLE:
        print("\n5. AI Server Test (Dummy Mode):")
        client = AIServerClient(ServerConfig(dummy_mode=True))
        test_texts = ["안녕하세요", "오늘 날씨", "이름이 뭐예요"]
        for text in test_texts:
            response = client.send_chat_request(text)
            print(f"   Q: {text}")
            print(f"   A: {response.ai_response} ({response.response_time:.2f}s)")
        client.close()

    print("\n=== Test Complete ===")


if __name__ == "__main__":
    test_system()
