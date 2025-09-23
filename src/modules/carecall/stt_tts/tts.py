#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tts.py
TTS 엔진 기능 모듈 - 로컬/원격 TTS 처리
"""

import os
import sys
import time
import tempfile
import subprocess
import threading
from typing import Optional, Dict, Any, Callable
import logging

# OpenAI TTS
try:
    import openai
except ImportError:
    openai = None

# 상위 디렉토리에서 config import
sys.path.append(os.path.join(os.path.dirname(__file__), '.'))
from config import get_config


class TTSEngine:
    """TTS 엔진 기본 클래스"""

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)

    def speak(self, text: str) -> bool:
        """텍스트를 음성으로 변환하여 재생"""
        raise NotImplementedError

    def synthesize(self, text: str, output_file: str) -> bool:
        """텍스트를 음성 파일로 저장"""
        raise NotImplementedError


class OpenAITTSEngine(TTSEngine):
    """OpenAI TTS 엔진"""

    def __init__(self, api_key: str, model: str = "tts-1", voice: str = "nova"):
        super().__init__()

        if openai is None:
            raise ImportError("openai library not available")

        if not api_key or api_key == "YOUR_API_KEY_HERE":
            raise ValueError("OpenAI API key not set")

        # OpenAI Python SDK v1 스타일
        self.client = openai.OpenAI(api_key=api_key)
        self.model = model
        self.voice = voice

    def synthesize(self, text: str, output_file: str) -> bool:
        """텍스트를 음성 파일로 저장"""
        try:
            response = self.client.audio.speech.create(
                model=self.model,
                voice=self.voice,
                input=text
            )
            response.stream_to_file(output_file)
            return os.path.exists(output_file)

        except Exception as e:
            self.logger.error(f"OpenAI TTS synthesis error: {e}")
            return False

    def speak(self, text: str) -> bool:
        """텍스트를 음성으로 변환하여 재생"""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
            audio_path = tmp_file.name

        try:
            # 음성 합성
            if not self.synthesize(text, audio_path):
                return False

            # 재생 (ffplay 사용)
            subprocess.run(
                ["ffplay", "-autoexit", "-nodisp", audio_path],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return True

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Audio playback failed: {e}")
            return False
        except Exception as e:
            self.logger.error(f"OpenAI TTS error: {e}")
            return False
        finally:
            try:
                os.unlink(audio_path)
            except Exception:
                pass


class TTSManager:
    """TTS 매니저 - OpenAI TTS 전용"""

    def __init__(self, config=None):
        self.config = config or get_config()

        if openai is None:
            raise ImportError("openai library not available")

        if not getattr(self.config, "openai", None) or not self.config.openai.api_key:
            raise ValueError("OpenAI API key not configured")

        self.tts_engine = OpenAITTSEngine(
            self.config.openai.api_key,
            getattr(self.config.openai, "tts_model", "tts-1"),
            getattr(self.config.openai, "tts_voice", "nova"),
        )
        self.engine_type = "openai"

        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info(f"TTS Manager initialized with {self.engine_type} engine")

    def speak(self, text: str) -> bool:
        """직접 음성 출력"""
        if not text or not text.strip():
            return False
        return self.tts_engine.speak(text)

    def synthesize(self, text: str, output_file: str) -> bool:
        """음성 파일로 저장"""
        return self.tts_engine.synthesize(text, output_file)

    def speak_async(self, text: str, callback: Optional[Callable] = None):
        """비동기 음성 출력"""
        def _speak():
            try:
                result = self.speak(text)
                if callback:
                    callback(result)
            except Exception as e:
                self.logger.error(f"Async speak error: {e}")
                if callback:
                    callback(False)

        thread = threading.Thread(target=_speak, daemon=True)
        thread.start()
        return thread

    def close(self):
        """리소스 정리 (필요시)"""
        pass


# tts.py 내 LocalCommandHandler 클래스를 아래로 교체

class LocalCommandHandler:
    """로컬 명령어 처리기"""
    def __init__(self, tts_manager: TTSManager):
        self.tts = tts_manager
        self.logger = logging.getLogger(self.__class__.__name__)

        # ✨ 필러 문구 리스트 추가 (AttributeError 원인 제거)
        self.filler_phrases = [
            "음... 생각해보는 중이에요.",
            "잠시만요, 확인해볼게요.",
            "조금만 기다려 주세요.",
            "알아보고 있어요.",
        ]

        # 로컬 명령어 매핑
        self.commands = {
            "지금 몇 시": self._handle_time,
            "현재 시간": self._handle_time,
            "오늘 날짜": self._handle_date,
            "오늘 몇일": self._handle_date,
            "고마워": self._handle_thanks,
            "고맙다": self._handle_thanks,
            "감사": self._handle_thanks,
            "잘가": self._handle_goodbye,
            "안녕": self._handle_goodbye,
            "종료": self._handle_exit,
            "끝": self._handle_exit,
            "멈춰": self._handle_exit,
        }

    def get_filler_phrase(self) -> str:
        import random
        return random.choice(self.filler_phrases)

    def _handle_time(self):
        from datetime import datetime
        now = datetime.now()
        return f"지금은 {now.hour}시 {now.minute}분입니다."

    def _handle_date(self):
        from datetime import datetime
        now = datetime.now()
        return f"오늘은 {now.month}월 {now.day}일입니다."

    def _handle_thanks(self):
        import random
        responses = [
            "천만에요. 더 도와드릴 일이 있을까요?",
            "별말씀을요. 언제든 말씀하세요.",
            "제가 도움이 되어서 기뻐요.",
            "당연하죠. 또 궁금한 게 있으면 물어보세요.",
        ]
        return random.choice(responses)

    def _handle_goodbye(self):
        import random
        responses = [
            "안녕히 가세요.",
            "다음에 또 만나요.",
            "좋은 하루 보내세요.",
            "언제든 다시 불러주세요.",
        ]
        return random.choice(responses)

    def _handle_exit(self):
        return "네 알겠습니다. 안녕히 계세요."

    def check_command(self, text: str) -> Optional[str]:
        text = text.strip()
        for keyword, handler in self.commands.items():
            if keyword in text:
                try:
                    response = handler()
                    self.logger.info(f"Local command handled: {keyword} -> {response}")
                    return response
                except Exception as e:
                    self.logger.error(f"Local command error: {e}")
                    return "죄송합니다. 처리 중 오류가 발생했습니다."
        return None

    def is_exit_command(self, text: str) -> bool:
        exit_keywords = ["종료", "끝", "멈춰", "그만", "exit", "quit"]
        return any(keyword in text for keyword in exit_keywords)



# 편의 함수들
def create_tts_manager() -> TTSManager:
    """TTS 매니저 생성 - OpenAI TTS 전용"""
    return TTSManager()


def test_tts():
    """TTS 시스템 테스트"""
    print("TTS 시스템 테스트 시작...")

    manager = create_tts_manager()
    test_texts = [
        "안녕하세요. TTS 테스트입니다.",
        "지금 몇 시인지 알려드릴까요?",
        "음성 합성이 잘 되고 있나요?",
    ]

    for text in test_texts:
        print(f"Speaking: {text}")
        result = manager.speak(text)
        print(f"Result: {result}")
        time.sleep(1)

    manager.close()
    print("TTS 테스트 완료")


if __name__ == "__main__":
    test_tts()
