# emotion_engine.py
import os
import math
from typing import Dict, Optional, List

import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification, pipeline

LABEL_MAP_TEXT = {
    # 모델 카드 기준 (dlckdfuf141/korean-emotion-kluebert-v2)
    0: "fear",  # 공포
    1: "surprise",
    2: "anger",
    3: "sad",
    4: "neutral",
    5: "happy",
    6: "disgust",
}

LABEL_CANON = ["neutral", "happy", "sad", "anger", "fear", "surprise", "disgust"]

def _softmax(xs: List[float]) -> List[float]:
    m = max(xs)
    exps = [math.exp(x - m) for x in xs]
    s = sum(exps)
    return [e / s for e in exps]

class EmotionEngine:
    """
    텍스트 + (선택) 음성 감정 분류 후 가중 통합.
    사용:
        emo = engine.infer(text="오늘 기분 좋아", audio=None, sr=16000)
        # -> {'label': 'happy', 'scores': {'happy':0.82,...}, 'text':..., 'audio':...}
    """

    def __init__(self,
                 text_model: str = None,
                 audio_model: Optional[str] = None,
                 device: Optional[str] = None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")

        # --- 텍스트 분류기 준비 ---
        self.text_model_name = text_model or os.getenv("EMO_TEXT_MODEL", "dlckdfuf141/korean-emotion-kluebert-v2")
        self._text_pipe = pipeline(
            "text-classification",
            model=AutoModelForSequenceClassification.from_pretrained(self.text_model_name),
            tokenizer=AutoTokenizer.from_pretrained(self.text_model_name),
            top_k=None,
            device=0 if self.device == "cuda" else -1,
            truncation=True
        )

        # --- 음성 분류기(선택) ---
        self.audio_enabled = bool(int(os.getenv("EMO_AUDIO_ENABLED", "0")))
        self.audio_model_name = audio_model or os.getenv("EMO_AUDIO_MODEL", "superb/wav2vec2-base-superb-er")
        self._audio_pipe = None
        if self.audio_enabled:
            try:
                self._audio_pipe = pipeline(
                    "audio-classification",
                    model=self.audio_model_name,
                    top_k=None,
                    device=0 if self.device == "cuda" else -1
                )
            except Exception:
                # 음성 모델 로드 실패해도 텍스트만 사용
                self.audio_enabled = False

        # late fusion 가중치
        self.alpha_text = float(os.getenv("EMO_FUSE_ALPHA_TEXT", "0.7"))  # 텍스트 0.7
        self.beta_audio = float(os.getenv("EMO_FUSE_BETA_AUDIO", "0.3"))  # 오디오 0.3

        # 저신뢰 텍스트일 때 오디오 비중 상향
        self.low_conf_boost = float(os.getenv("EMO_LOWCONF_BOOST", "0.15"))
        self.low_conf_thresh = float(os.getenv("EMO_LOWCONF_THRESH", "0.50"))

        # 지수이동평균(턴별 스무딩)
        self.smooth_gamma = float(os.getenv("EMO_SMOOTH_GAMMA", "0.2"))
        self._ema_scores = None  # type: Optional[Dict[str, float]]

    # --- 내부 유틸 ---
    def _canon_scores(self, labels: List[str], scores: List[float], kind: str) -> Dict[str, float]:
        out = {k: 0.0 for k in LABEL_CANON}
        if kind == "text":
            # 라벨이 id로 오면 변환
            for lab, sc in zip(labels, scores):
                name = lab
                if isinstance(lab, int):
                    name = LABEL_MAP_TEXT.get(lab, "neutral")
                name = name.lower()
                if name in out:
                    out[name] = max(out[name], sc)
        else:
            # audio 모델 라벨을 canonical로 매핑(모델별 다름 → 단순 매핑)
            # SUPERB-ER 대부분: angry/happy/sad/neutral 등
            for lab, sc in zip(labels, scores):
                name = lab.lower()
                if "ang" in name:
                    out["anger"] = max(out["anger"], sc)
                elif "hap" in name or "joy" in name:
                    out["happy"] = max(out["happy"], sc)
                elif "sad" in name:
                    out["sad"] = max(out["sad"], sc)
                elif "fear" in name:
                    out["fear"] = max(out["fear"], sc)
                elif "surpr" in name:
                    out["surprise"] = max(out["surprise"], sc)
                elif "disgust" in name:
                    out["disgust"] = max(out["disgust"], sc)
                else:
                    out["neutral"] = max(out["neutral"], sc)
        # 정규화
        vals = list(out.values())
        if sum(vals) > 0:
            sm = sum(vals)
            for k in out:
                out[k] /= sm
        else:
            out["neutral"] = 1.0
        return out

    def _infer_text(self, text: str) -> Dict[str, float]:
        if not (text and text.strip()):
            return {k: (1.0 if k == "neutral" else 0.0) for k in LABEL_CANON}
        res = self._text_pipe(text, truncation=True)
        # transformers>=4.40 top_k=None: 리스트[{'label':..., 'score':...}, ...] or batched
        if isinstance(res, list) and len(res) and isinstance(res[0], dict):
            labels = [r["label"] if "label" in r else r.get("id", 4) for r in res]
            scores = [float(r["score"]) for r in res]
        else:
            labels = [4]
            scores = [1.0]
        return self._canon_scores(labels, scores, "text")

    def _infer_audio(self, audio_bytes: bytes, sr: int = 16000) -> Dict[str, float]:
        if not (self.audio_enabled and self._audio_pipe and audio_bytes):
            return {k: 0.0 for k in LABEL_CANON} | {"neutral": 1.0}
        try:
            # pipeline은 파일 경로나 배열을 기대 — bytes는 메모리 파일로 건넴
            import tempfile, soundfile as sf, numpy as np, io
            data = np.frombuffer(audio_bytes, dtype="<i2").astype("float32") / 32768.0
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as f:
                sf.write(f.name, data, sr, subtype="PCM_16")
                out = self._audio_pipe(f.name)
        except Exception:
            return {k: 0.0 for k in LABEL_CANON} | {"neutral": 1.0}

        # out: [{'label':'angry', 'score':0.7}, ...]
        labels = [o["label"] for o in out]
        scores = [float(o["score"]) for o in out]
        # softmax 보정(혹시 모델이 raw logits일 경우)
        if max(scores) > 1.0:
            scores = _softmax(scores)
        return self._canon_scores(labels, scores, "audio")

    def _fuse(self, s_text: Dict[str, float], s_audio: Dict[str, float]) -> Dict[str, float]:
        # 텍스트 최댓값이 낮으면 오디오 가중치 보정
        tmax = max(s_text.values()) if s_text else 0.0
        alpha = self.alpha_text
        beta = self.beta_audio
        if tmax < self.low_conf_thresh:
            beta = min(1.0, beta + self.low_conf_boost)
            alpha = max(0.0, 1.0 - beta)
        fused = {}
        for k in LABEL_CANON:
            fused[k] = alpha * s_text.get(k, 0.0) + beta * s_audio.get(k, 0.0)
        # 정규화
        sm = sum(fused.values())
        if sm > 0:
            for k in fused:
                fused[k] /= sm
        return fused

    def _smooth(self, scores: Dict[str, float]) -> Dict[str, float]:
        g = self.smooth_gamma
        if g <= 0 or self._ema_scores is None:
            self._ema_scores = scores.copy()
            return scores
        for k in LABEL_CANON:
            self._ema_scores[k] = (1 - g) * self._ema_scores[k] + g * scores[k]
        # 정규화
        sm = sum(self._ema_scores.values())
        if sm > 0:
            for k in self._ema_scores:
                self._ema_scores[k] /= sm
        return self._ema_scores.copy()

    def infer(self, text: str, audio: Optional[bytes] = None, sr: int = 16000) -> Dict[str, object]:
        s_text = self._infer_text(text)
        s_audio = self._infer_audio(audio, sr) if self.audio_enabled else {k: 0.0 for k in LABEL_CANON} | {"neutral": 1.0}
        fused = self._fuse(s_text, s_audio)
        smoothed = self._smooth(fused)
        label = max(smoothed, key=smoothed.get)
        return {
            "label": label,
            "scores": smoothed,
            "text": s_text,
            "audio": s_audio,
        }
