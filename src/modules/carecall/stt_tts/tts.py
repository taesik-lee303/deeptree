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
    """필러 문구 제공기 (로컬 명령어 처리 제거)"""
    def __init__(self, tts_manager: TTSManager, conversation_manager=None):
        self.tts = tts_manager
        self.logger = logging.getLogger(self.__class__.__name__)

        # 필러 문구 리스트
        self.filler_phrases = [
            "음... 생각해보는 중이에요.",
            "잠시만요, 확인해볼게요.",
            "조금만 기다려 주세요.",
            "알아보고 있어요.",
        ]

    def get_filler_phrase(self) -> str:
        import random
        return random.choice(self.filler_phrases)



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
