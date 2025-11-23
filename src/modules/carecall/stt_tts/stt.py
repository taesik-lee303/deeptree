#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stt.py
Whisper STT 기능 모듈 - OpenAI Whisper API 전용
"""

import os
import sys
import time
import threading
import queue
from typing import Optional, Callable
import logging

import numpy as np
import sounddevice as sd
import webrtcvad

# OpenAI Whisper (원격)
try:
    import openai
except ImportError:
    openai = None

# 상위 디렉토리에서 config import
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from config import get_config


class STTEngine:
    """STT 엔진 기본 클래스"""

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)

    def transcribe(self, audio_data: bytes, sample_rate: int = 16000) -> str:
        """오디오 데이터를 텍스트로 변환"""
        raise NotImplementedError

    def transcribe_file(self, file_path: str) -> str:
        """오디오 파일을 텍스트로 변환"""
        raise NotImplementedError


class WhisperRemoteEngine(STTEngine):
    """OpenAI Whisper API STT 엔진"""

    def __init__(self, api_key: str, model: str = "whisper-1"):
        super().__init__()

        if openai is None:
            raise ImportError("openai library not available")

        if not api_key or api_key == "YOUR_API_KEY_HERE":
            raise ValueError("OpenAI API key not set")

        self.client = openai.OpenAI(api_key=api_key)
        self.model = model
        self.logger.info(f"OpenAI Whisper initialized with model: {model}")

    # -------------------------
    # 기본 텍스트만 반환 (기존 호환)
    # -------------------------
    def transcribe_file(self, file_path: str) -> str:
        """오디오 파일을 OpenAI API로 변환 (텍스트만)"""
        try:
            with open(file_path, "rb") as audio_file:
                transcript = self.client.audio.transcriptions.create(
                    model=self.model,
                    file=audio_file,
                    language="ko"
                )
            return transcript.text
        except Exception as e:
            self.logger.error(f"OpenAI STT error: {e}")
            return ""

    def transcribe(self, audio_data: bytes, sample_rate: int = 16000) -> str:
        """바이트 데이터를 임시 파일로 저장 후 API 호출 (텍스트만)"""
        import tempfile
        import wave
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
                with wave.open(tmp_file.name, 'wb') as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)  # 16-bit
                    wav_file.setframerate(sample_rate)
                    wav_file.writeframes(audio_data)
                result = self.transcribe_file(tmp_file.name)
            os.unlink(tmp_file.name)
            return result
        except Exception as e:
            self.logger.error(f"Remote transcription error: {e}")
            return ""

    # -------------------------
    # verbose_json 반환 (no_speech_prob 필터링용)
    # -------------------------
    def transcribe_file_verbose(self, file_path: str) -> dict:
        """verbose_json으로 받아 메타 포함 반환"""
        try:
            with open(file_path, "rb") as audio_file:
                transcript = self.client.audio.transcriptions.create(
                    model=self.model,
                    file=audio_file,
                    language="ko",
                    response_format="verbose_json",
                    temperature=0.0
                )
            # transcript는 pydantic 객체처럼 동작할 수 있으니 dict로 정규화
            data = {
                "text": getattr(transcript, "text", "") or "",
                "segments": [s.__dict__ if hasattr(s, "__dict__") else dict(s) for s in getattr(transcript, "segments", [])] if hasattr(transcript, "segments") else [],
                "duration": getattr(transcript, "duration", None)
            }
            return data
        except Exception as e:
            self.logger.error(f"OpenAI STT verbose_json error: {e}")
            return {"text": "", "segments": [], "duration": None}

    def transcribe_verbose(self, audio_data: bytes, sample_rate: int = 16000) -> dict:
        """바이트 데이터를 임시 파일로 저장 후 verbose_json으로 호출"""
        import tempfile
        import wave
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
                with wave.open(tmp_file.name, 'wb') as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)  # 16-bit
                    wav_file.setframerate(sample_rate)
                    wav_file.writeframes(audio_data)
                result = self.transcribe_file_verbose(tmp_file.name)
            os.unlink(tmp_file.name)
            return result
        except Exception as e:
            self.logger.error(f"Remote transcription verbose error: {e}")
            return {"text": "", "segments": [], "duration": None}


class VADAudioCapture:
    """VAD 기반 오디오 캡처 (WebRTC VAD 게이트로 '사람 목소리'만 발화로 인정)"""

    def __init__(self, config=None, on_speech_detected: Optional[Callable] = None,
                 on_speech_ended: Optional[Callable[[bytes], None]] = None):
        self.config = config or get_config()
        self.audio_config = self.config.audio

        self.on_speech_detected = on_speech_detected
        self.on_speech_ended = on_speech_ended

        # WebRTC VAD 초기화 (공격성 0~3)
        self.vad = webrtcvad.Vad(int(self.audio_config.vad_aggressiveness))
        # 사람 목소리만 통과시킬지
        self.human_only = os.getenv("HUMAN_ONLY", "1") != "0"  # HUMAN_ONLY=0 이면 비활성

        # 오디오 스트림 설정
        self.target_rate = self.audio_config.sample_rate  # 16000 for Whisper and VAD
        self.native_rate = None  # To be determined dynamically

        # 프레임/버퍼/타임아웃
        self.frame_ms = int(self.audio_config.frame_ms)
        if self.frame_ms not in (10, 20, 30):
            logging.getLogger(self.__class__.__name__).warning(
                "frame_ms=%s는 WebRTC VAD에서 지원되지 않아 20ms로 강제합니다.", self.frame_ms
            )
            self.frame_ms = 20
        self.vad_frame_bytes = int(self.target_rate * (self.frame_ms / 1000.0)) * 2
        self.pre_max_bytes = int(self.target_rate * (self.audio_config.pre_silence_ms / 1000.0)) * 2
        self.utterance_timeout_s = 10.0  # 발화 타임아웃 (10초)

        # 상태 변수
        self.is_capturing = False
        self.pre_buffer = bytearray()
        self.voice_buffer = bytearray()
        self.silence_ms = 0
        self.voicing = False
        self.speech_start_time = 0

        # 연속 human 프레임 누적 시간 & 기준
        self.voiced_ms = 0
        self.min_human_ms =  int(os.getenv("MIN_HUMAN_MS", str(getattr(self.audio_config, "min_human_ms", 150))))  # 200~300 권장
        self.end_silence_ms = int(os.getenv("END_SILENCE_MS", str(getattr(self.audio_config, "end_silence_ms", 700))))

        # STT 재개 직후 쿨다운 (잔향/클릭 무시)
        self.resume_cooldown_ms = int(os.getenv("RESUME_COOLDOWN_MS", "0"))
        self._cooldown_until = 0.0

        self.logger = logging.getLogger(self.__class__.__name__)

    def _choose_device(self, device_str: Optional[str]):
        """디바이스 선택"""
        if not device_str:
            return None
        try:
            return int(device_str)
        except ValueError:
            try:
                for i, d in enumerate(sd.query_devices()):
                    name = d.get("name", "")
                    if device_str.lower() in name.lower():
                        return i
            except Exception:
                pass
            return None

    def _resample_audio(self, audio_bytes: bytes, input_rate: int, output_rate: int) -> bytes:
        """오디오 리샘플링 (선형 보간)"""
        if input_rate == output_rate:
            return audio_bytes

        audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
        x = np.arange(len(audio_array))
        new_len = int(len(audio_array) * output_rate / input_rate)
        audio_array = np.interp(np.linspace(0, len(audio_array) - 1, new_len), x, audio_array).astype(np.int16)
        return audio_array.tobytes()

    # ---------------------------
    # 사람 목소리 게이트 핵심 처리
    # ---------------------------
    def _process_pcm_bytes(self, pcm_bytes: bytes):
        """
        16kHz mono int16 PCM을 frame_ms씩 쪼개 WebRTC VAD로 '사람 목소리'만 발화로 인정.
        - voicing False: pre_buffer만 유지 (선행 몇백 ms)
        - voicing True : voice_buffer에 누적, end_silence_ms 충족 시 종료
        """
        import time as _t

        # 재개 직후 쿨다운 동안은 무시
        if self.resume_cooldown_ms and _t.monotonic() < self._cooldown_until:
            return

        fb = self.vad_frame_bytes
        i = 0

        while i + fb <= len(pcm_bytes):
            frame = pcm_bytes[i:i + fb]
            i += fb

            # 사람 목소리 여부
            is_human = True
            if self.human_only:
                try:
                    is_human = self.vad.is_speech(frame, self.target_rate)
                except Exception:
                    is_human = True  # VAD 오류 시 통과

            if is_human:
                self.voiced_ms += self.frame_ms
                self.silence_ms = 0

                if not self.voicing and self.voiced_ms >= self.min_human_ms:
                    # 발화 시작
                    self.voicing = True
                    self.speech_start_time = time.time()
                    if self.on_speech_detected:
                        try:
                            self.on_speech_detected()
                        except Exception:
                            pass
                    if self.pre_buffer:
                        self.voice_buffer.extend(self.pre_buffer)
                        self.pre_buffer.clear()

                if self.voicing:
                    self.voice_buffer.extend(frame)

                # 최대 발화 길이 초과 시 강제 종료
                if self.voicing and (time.time() - self.speech_start_time) >= self.utterance_timeout_s:
                    self.logger.info(f"Utterance timeout of {self.utterance_timeout_s}s reached. Forcing end of speech.")
                    if self.on_speech_ended and self.voice_buffer:
                        try:
                            self.on_speech_ended(bytes(self.voice_buffer))
                        except Exception:
                            pass
                    self.voice_buffer.clear()
                    self.voicing = False
                    self.voiced_ms = 0
                    self.silence_ms = 0

            else:
                if not self.voicing:
                    # 아직 시작 전: pre_buffer만 슬라이딩 유지
                    self.pre_buffer.extend(frame)
                    if len(self.pre_buffer) > self.pre_max_bytes:
                        del self.pre_buffer[:len(self.pre_buffer) - self.pre_max_bytes]
                    self.voiced_ms = 0
                else:
                    # 말하는 중: 무음 누적 (trailing 약간 포함하려면 아래 라인 유지)
                    self.silence_ms += self.frame_ms
                    self.voice_buffer.extend(frame)

                    if self.silence_ms >= self.end_silence_ms:
                        if self.on_speech_ended and self.voice_buffer:
                            try:
                                self.on_speech_ended(bytes(self.voice_buffer))
                            except Exception:
                                pass
                        self.voice_buffer.clear()
                        self.voicing = False
                        self.voiced_ms = 0
                        self.silence_ms = 0

    def _audio_callback(self, indata, frames, time_info, status):
        """오디오 스트림 콜백"""
        if frames <= 0 or not self.is_capturing:
            return

        try:
            resampled_audio = self._resample_audio(indata.tobytes(), self.native_rate, self.target_rate)
            # 사람 목소리 게이트 처리
            self._process_pcm_bytes(resampled_audio)

        except Exception as e:
            self.logger.error(f"Audio callback error: {e}")
            return

    def start_capture(self):
        """오디오 캡처 시작"""
        if self.is_capturing:
            return

        self.is_capturing = True
        device_idx = self._choose_device(self.audio_config.input_device)

        try:
            device_info = sd.query_devices(device_idx)
            self.native_rate = int(device_info['default_samplerate'])
        except Exception as e:
            self.logger.error(f"Could not get device info, falling back to system default. Error: {e}")
            self.native_rate = int(sd.query_devices(device_idx)['default_samplerate'])

        self.stream = sd.InputStream(
            samplerate=self.native_rate,
            blocksize=int(self.native_rate * (self.frame_ms / 1000.0)),
            channels=1,
            dtype="int16",
            callback=self._audio_callback,
            latency="low",
            device=device_idx,
        )

        # 재개 쿨다운 타이머
        if self.resume_cooldown_ms:
            import time as _t
            self._cooldown_until = _t.monotonic() + (self.resume_cooldown_ms / 1000.0)

        self.stream.start()
        self.logger.info(
            f"Audio capture started (device={device_idx}, native_rate={self.native_rate}, target_rate={self.target_rate})"
        )

    def stop_capture(self):
        """오디오 캡처 중지"""
        if not self.is_capturing:
            return

        self.is_capturing = False
        if hasattr(self, 'stream'):
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass

        self.logger.info("Audio capture stopped")


class STTManager:
    """STT 매니저 - OpenAI Whisper API 전용"""

    def __init__(self, config=None):
        self.config = config or get_config()

        # OpenAI Whisper 엔진 초기화
        if not self.config.openai.api_key or self.config.openai.api_key == "YOUR_OPENAI_API_KEY_HERE":
            raise ValueError("OpenAI API key is required for STT")

        self.stt_engine = WhisperRemoteEngine(
            self.config.openai.api_key,
            self.config.whisper.model
        )

        # VAD 캡처 초기화
        self.audio_capture = VADAudioCapture(
            config=self.config,
            on_speech_detected=self._on_speech_detected,
            on_speech_ended=self._on_speech_ended
        )

        # 작업 큐와 워커
        self.work_queue = queue.Queue()
        self.worker = None
        self.is_running = False

        # Whisper 필터 설정
        self.no_speech_thresh = float(os.getenv("NO_SPEECH_THRESH", "0.6"))
        self.min_text_len = int(os.getenv("MIN_TEXT_LEN", "1"))  # 너무 짧은 텍스트 거르기

        self.logger = logging.getLogger(self.__class__.__name__)

    def _on_speech_detected(self):
        """음성 감지됨"""
        self.logger.info("Speech detected (human)")

    def _on_speech_ended(self, audio_data: bytes):
        """음성 종료됨"""
        self.logger.info("Speech ended, queuing for transcription")
        self.work_queue.put(audio_data)

    def _transcription_worker(self):
        """전사 워커 스레드 (verbose_json으로 2차 필터링)"""
        while self.is_running:
            try:
                audio_data = self.work_queue.get(timeout=1)
                if audio_data is None:  # 종료 신호
                    break

                # --- verbose_json으로 호출 ---
                result = self.stt_engine.transcribe_verbose(
                    audio_data, self.config.audio.sample_rate
                )
                text = (result.get("text") or "").strip()
                segments = result.get("segments") or []

                # no_speech_prob 최대값 계산
                max_nsp = 0.0
                for seg in segments:
                    nsp = seg.get("no_speech_prob")
                    if isinstance(nsp, (int, float)):
                        if nsp > max_nsp:
                            max_nsp = nsp

                # 1) 사람 말 아님(Whisper 판단) → 필터링
                if max_nsp >= self.no_speech_thresh:
                    self.logger.info(f"Filtered non-speech by Whisper (no_speech_prob={max_nsp:.2f})")
                    self.work_queue.task_done()
                    continue

                # 2) 너무 짧은 텍스트도 필터링(선택)
                if len(text) < self.min_text_len:
                    self.logger.info("Filtered too-short transcription")
                    self.work_queue.task_done()
                    continue

                if text:
                    self.logger.info(f"Transcribed: {text}")

                    # 콜백 호출 (있다면)
                    if hasattr(self, 'on_transcribed') and self.on_transcribed:
                        try:
                            self.on_transcribed(text)
                        except Exception as e:
                            self.logger.error(f"on_transcribed callback error: {e}")

                self.work_queue.task_done()

            except queue.Empty:
                continue
            except Exception as e:
                self.logger.error(f"Transcription worker error: {e}")

    def start(self, on_transcribed: Optional[Callable[[str], None]] = None):
        """STT 시스템 시작 - 완전한 재시작 보장"""
        if self.is_running:
            self.logger.warning("STT Manager is already running, stopping before restart")
            self.stop()
            # 정리 대기 (더 긴 대기 시간)
            time.sleep(0.5)
            # 상태 재확인
            if self.is_running or (hasattr(self, 'worker') and self.worker and self.worker.is_alive()):
                self.logger.error("STT Manager did not stop properly, forcing cleanup")
                self.is_running = False
                if hasattr(self, 'worker'):
                    self.worker = None
                time.sleep(0.3)

        # 시작 전 상태 확인
        if self.is_running:
            self.logger.error("STT Manager is still marked as running, cannot start")
            return

        self.logger.info("Starting STT Manager...")
        self.is_running = True
        self.on_transcribed = on_transcribed

        # 워커 스레드 시작
        try:
            self.worker = threading.Thread(target=self._transcription_worker, daemon=True)
            self.worker.start()
            self.logger.info("STT worker thread started")
        except Exception as e:
            self.logger.error(f"Failed to start STT worker thread: {e}")
            self.is_running = False
            raise

        # 오디오 캡처 시작
        try:
            self.audio_capture.start_capture()
            self.logger.info("Audio capture started")
        except Exception as e:
            self.logger.error(f"Failed to start audio capture: {e}")
            self.is_running = False
            if self.worker:
                self.work_queue.put(None)
            raise

        self.logger.info("STT Manager started successfully")

    def stop(self):
        """STT 시스템 중지 - 완전한 정리를 보장"""
        if not self.is_running:
            self.logger.debug("STT Manager already stopped")
            return

        self.logger.info("Stopping STT Manager...")
        self.is_running = False

        # 오디오 캡처 중지
        try:
            self.audio_capture.stop_capture()
            # 오디오 캡처가 완전히 정리될 때까지 대기
            time.sleep(0.3)
        except Exception as e:
            self.logger.warning(f"Error stopping audio capture: {e}")

        # 워커 종료
        try:
            self.work_queue.put(None)
            if self.worker and self.worker.is_alive():
                self.worker.join(timeout=5)
                if self.worker.is_alive():
                    self.logger.warning("STT worker thread did not terminate within timeout")
        except Exception as e:
            self.logger.warning(f"Error stopping worker: {e}")

        # 상태 확인 및 정리
        if hasattr(self, 'worker'):
            self.worker = None
        if hasattr(self, 'on_transcribed'):
            self.on_transcribed = None

        self.logger.info("STT Manager stopped completely")

    def transcribe_file(self, file_path: str) -> str:
        """파일 직접 전사 (텍스트)"""
        return self.stt_engine.transcribe_file(file_path)

    def transcribe_audio(self, audio_data: bytes, sample_rate: int = 16000) -> str:
        """오디오 데이터 직접 전사 (텍스트)"""
        return self.stt_engine.transcribe(audio_data, sample_rate)


# 편의 함수들
def create_stt_manager() -> STTManager:
    """STT 매니저 생성"""
    return STTManager()


def test_stt():
    """STT 시스템 테스트"""
    print("STT 시스템 테스트 시작...")

    def on_result(text):
        print(f"인식된 텍스트: {text}")

    try:
        manager = create_stt_manager()

        manager.start(on_result)
        print("음성 인식 중... Ctrl+C로 종료")

        while True:
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("종료 중...")
    except Exception as e:
        print(f"오류: {e}")
    finally:
        if 'manager' in locals():
            manager.stop()


if __name__ == "__main__":
    test_stt()
