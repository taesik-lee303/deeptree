"""
열화상 이미지에서 건강 정보를 추출하는 모듈

추출 가능한 건강 정보:
1. 체온 (Forehead temperature)
2. 심박수 (Heart rate via thermal rPPG)
3. 호흡수 (Respiration rate)
4. 스트레스 지수 (Stress index)
5. 혈류 상태 (Blood flow status)
"""

import logging
import numpy as np
from scipy import signal
from typing import Optional, List, Tuple
from dataclasses import dataclass, field
from collections import deque
import time

logger = logging.getLogger(__name__)


@dataclass
class HealthMetrics:
    """건강 지표 데이터 클래스"""
    timestamp: float
    body_temperature: float  # 체온 (Celsius)
    heart_rate: Optional[float] = None  # 심박수 (bpm)
    respiration_rate: Optional[float] = None  # 호흡수 (breaths/min)
    stress_index: Optional[float] = None  # 스트레스 지수 (0-1)
    blood_flow_status: Optional[str] = None  # 혈류 상태: "normal", "low", "high"
    fever_detected: bool = False  # 발열 감지
    confidence: float = 0.0  # 측정 신뢰도
    
    def to_dict(self) -> dict:
        """딕셔너리로 변환"""
        return {
            'timestamp': self.timestamp,
            'body_temperature': self.body_temperature,
            'heart_rate': self.heart_rate,
            'respiration_rate': self.respiration_rate,
            'stress_index': self.stress_index,
            'blood_flow_status': self.blood_flow_status,
            'fever_detected': self.fever_detected,
            'confidence': self.confidence
        }


class HealthExtractor:
    """
    열화상 이미지에서 건강 정보를 추출하는 클래스
    
    방법:
    1. 체온: 이마 영역의 평균 온도 측정
    2. 심박수: 열화상 rPPG (remote photoplethysmography) 기법 사용
    3. 호흡수: 코/입 주변 온도 변화 분석
    4. 스트레스: 얼굴 온도 분포 및 변동성 분석
    """
    
    # 정상 범위
    NORMAL_TEMP_MIN = 36.0  # 정상 체온 최소값
    NORMAL_TEMP_MAX = 37.5  # 정상 체온 최대값
    FEVER_THRESHOLD = 37.5  # 발열 기준
    NORMAL_HR_MIN = 60  # 정상 심박수 최소값
    NORMAL_HR_MAX = 100  # 정상 심박수 최대값
    
    def __init__(
        self,
        sampling_rate: float = 16.0,  # 샘플링 주파수 (Hz)
        hr_analysis_window: int = 64,  # 심박수 분석 윈도우 크기 (프레임)
        rr_analysis_window: int = 128,  # 호흡수 분석 윈도우 크기 (프레임)
        min_measurement_duration: float = 8.0  # 최소 측정 시간 (초)
    ):
        """
        Args:
            sampling_rate: 샘플링 주파수
            hr_analysis_window: 심박수 분석에 필요한 프레임 수
            rr_analysis_window: 호흡수 분석에 필요한 프레임 수
            min_measurement_duration: 최소 측정 시간
        """
        self.sampling_rate = sampling_rate
        self.hr_analysis_window = hr_analysis_window
        self.rr_analysis_window = rr_analysis_window
        self.min_measurement_duration = min_measurement_duration
        
        # 시간 시리즈 데이터 저장
        self.temperature_history = deque(maxlen=rr_analysis_window)
        self.forehead_temp_history = deque(maxlen=hr_analysis_window)
        self.cheek_temp_history = deque(maxlen=hr_analysis_window)
        self.nose_temp_history = deque(maxlen=rr_analysis_window)
        self.timestamps = deque(maxlen=rr_analysis_window)
        
        # 측정 시작 시간
        self.measurement_start_time = None
        
    def add_frame(
        self,
        temperature_array: np.ndarray,
        face_region,
        timestamp: float
    ):
        """
        새로운 프레임 추가 및 분석
        
        Args:
            temperature_array: 온도 배열
            face_region: FaceRegion 객체
            timestamp: 타임스탬프
        """
        if face_region is None:
            return
        
        # 측정 시작 시간 기록
        if self.measurement_start_time is None:
            self.measurement_start_time = timestamp
        
        # 얼굴 영역 온도 추출
        x, y, w, h = face_region.bbox
        
        # 이마 온도
        forehead_y, forehead_x = face_region.forehead_center
        forehead_temp = self._get_region_temperature(
            temperature_array, forehead_x, forehead_y, radius=2
        )
        
        # 뺨 온도 (평균)
        cheek_l_y, cheek_l_x = face_region.cheek_left
        cheek_r_y, cheek_r_x = face_region.cheek_right
        cheek_l_temp = self._get_region_temperature(
            temperature_array, cheek_l_x, cheek_l_y, radius=2
        )
        cheek_r_temp = self._get_region_temperature(
            temperature_array, cheek_r_x, cheek_r_y, radius=2
        )
        cheek_avg_temp = (cheek_l_temp + cheek_r_temp) / 2
        
        # 코 주변 온도
        nose_y, nose_x = face_region.nose_tip
        nose_temp = self._get_region_temperature(
            temperature_array, nose_x, nose_y, radius=2
        )
        
        # 전체 얼굴 평균 온도
        face_region_array = temperature_array[y:y+h, x:x+w]
        face_avg_temp = np.mean(face_region_array)
        
        # 히스토리 저장
        self.timestamps.append(timestamp)
        self.temperature_history.append(face_avg_temp)
        self.forehead_temp_history.append(forehead_temp)
        self.cheek_temp_history.append(cheek_avg_temp)
        self.nose_temp_history.append(nose_temp)
    
    def extract_health_metrics(self) -> Optional[HealthMetrics]:
        """
        건강 지표 추출
        
        Returns:
            HealthMetrics 객체 또는 None
        """
        if len(self.temperature_history) < 10:
            return None
        
        current_time = time.time()
        
        # 측정 시간 확인
        if self.measurement_start_time:
            measurement_duration = current_time - self.measurement_start_time
            if measurement_duration < self.min_measurement_duration:
                return None
        
        # 1. 체온 측정 (이마 온도)
        body_temp = self._estimate_body_temperature()
        
        # 2. 심박수 측정
        heart_rate = self._estimate_heart_rate()
        
        # 3. 호흡수 측정
        respiration_rate = self._estimate_respiration_rate()
        
        # 4. 스트레스 지수
        stress_index = self._estimate_stress_index()
        
        # 5. 혈류 상태
        blood_flow_status = self._estimate_blood_flow_status()
        
        # 6. 발열 감지
        fever_detected = body_temp >= self.FEVER_THRESHOLD
        
        # 7. 신뢰도 계산
        confidence = self._calculate_confidence()
        
        return HealthMetrics(
            timestamp=current_time,
            body_temperature=body_temp,
            heart_rate=heart_rate,
            respiration_rate=respiration_rate,
            stress_index=stress_index,
            blood_flow_status=blood_flow_status,
            fever_detected=fever_detected,
            confidence=confidence
        )
    
    def _get_region_temperature(
        self,
        temperature_array: np.ndarray,
        center_x: int,
        center_y: int,
        radius: int = 2
    ) -> float:
        """특정 영역의 평균 온도"""
        h, w = temperature_array.shape
        
        y1 = max(0, center_y - radius)
        y2 = min(h, center_y + radius + 1)
        x1 = max(0, center_x - radius)
        x2 = min(w, center_x + radius + 1)
        
        region = temperature_array[y1:y2, x1:x2]
        return float(np.mean(region))
    
    def _estimate_body_temperature(self) -> float:
        """체온 추정 (이마 온도 기반)"""
        if len(self.forehead_temp_history) == 0:
            return 0.0
        
        # 이마 온도의 중앙값 사용 (이상치 제거)
        temps = np.array(self.forehead_temp_history)
        median_temp = np.median(temps)
        
        # 최근 값들의 평균 (가중치)
        recent_temps = list(self.forehead_temp_history)[-10:]
        recent_avg = np.mean(recent_temps)
        
        # 중앙값과 평균의 가중 평균
        body_temp = median_temp * 0.6 + recent_avg * 0.4
        
        return float(body_temp)
    
    def _estimate_heart_rate(self) -> Optional[float]:
        """심박수 추정 (열화상 rPPG)"""
        if len(self.forehead_temp_history) < self.hr_analysis_window:
            return None
        
        # 이마 온도 시계열 (혈류 변화 반영)
        signal_data = np.array(self.forehead_temp_history)
        
        # 고주파 노이즈 제거
        b, a = signal.butter(3, [0.5, 3.0], btype='band', fs=self.sampling_rate)
        filtered_signal = signal.filtfilt(b, a, signal_data)
        
        # FFT를 통한 주파수 분석
        fft = np.fft.rfft(filtered_signal)
        freqs = np.fft.rfftfreq(len(filtered_signal), 1.0 / self.sampling_rate)
        
        # 심박수 범위: 0.7 Hz (42 bpm) ~ 3.5 Hz (210 bpm)
        hr_min_freq = 0.7
        hr_max_freq = 3.5
        
        mask = (freqs >= hr_min_freq) & (freqs <= hr_max_freq)
        if not np.any(mask):
            return None
        
        # 최대 파워 주파수 찾기
        power = np.abs(fft[mask])
        max_power_idx = np.argmax(power)
        dominant_freq = freqs[mask][max_power_idx]
        
        # Hz를 bpm으로 변환
        heart_rate = dominant_freq * 60.0
        
        # 정상 범위 검증
        if self.NORMAL_HR_MIN <= heart_rate <= self.NORMAL_HR_MAX * 1.5:
            return float(heart_rate)
        
        return None
    
    def _estimate_respiration_rate(self) -> Optional[float]:
        """호흡수 추정 (코/입 주변 온도 변화)"""
        if len(self.nose_temp_history) < self.rr_analysis_window:
            return None
        
        # 코 주변 온도 시계열 (호흡에 따른 온도 변화)
        signal_data = np.array(self.nose_temp_history)
        
        # 저주파 필터링 (호흡은 느린 변화)
        b, a = signal.butter(3, [0.1, 0.5], btype='band', fs=self.sampling_rate)
        filtered_signal = signal.filtfilt(b, a, signal_data)
        
        # FFT 분석
        fft = np.fft.rfft(filtered_signal)
        freqs = np.fft.rfftfreq(len(filtered_signal), 1.0 / self.sampling_rate)
        
        # 호흡수 범위: 0.1 Hz (6 breaths/min) ~ 0.5 Hz (30 breaths/min)
        rr_min_freq = 0.1
        rr_max_freq = 0.5
        
        mask = (freqs >= rr_min_freq) & (freqs <= rr_max_freq)
        if not np.any(mask):
            return None
        
        # 최대 파워 주파수
        power = np.abs(fft[mask])
        max_power_idx = np.argmax(power)
        dominant_freq = freqs[mask][max_power_idx]
        
        # Hz를 breaths/min으로 변환
        respiration_rate = dominant_freq * 60.0
        
        # 정상 범위: 12-20 breaths/min
        if 6 <= respiration_rate <= 30:
            return float(respiration_rate)
        
        return None
    
    def _estimate_stress_index(self) -> Optional[float]:
        """스트레스 지수 추정"""
        if len(self.temperature_history) < 20:
            return None
        
        temps = np.array(self.temperature_history)
        
        # 1. 온도 변동성 (스트레스 시 변동 증가)
        temp_std = np.std(temps)
        variability_score = min(1.0, temp_std / 1.0)  # 표준편차 1도면 최고 점수
        
        # 2. 온도 분포 비대칭성
        temp_skew = abs(self._skewness(temps))
        asymmetry_score = min(1.0, temp_skew / 2.0)
        
        # 3. 얼굴 온도 균일성 (스트레스 시 일부 영역 과열)
        if len(self.forehead_temp_history) > 0 and len(self.cheek_temp_history) > 0:
            forehead_temps = np.array(self.forehead_temp_history[-10:])
            cheek_temps = np.array(self.cheek_temp_history[-10:])
            temp_diff = np.mean(np.abs(forehead_temps - cheek_temps))
            uniformity_score = min(1.0, temp_diff / 2.0)
        else:
            uniformity_score = 0.0
        
        # 종합 스트레스 지수 (0-1)
        stress_index = (variability_score * 0.4 + asymmetry_score * 0.3 + uniformity_score * 0.3)
        
        return float(np.clip(stress_index, 0.0, 1.0))
    
    def _estimate_blood_flow_status(self) -> Optional[str]:
        """혈류 상태 추정"""
        if len(self.forehead_temp_history) < 10:
            return None
        
        # 이마 온도 변동성 (혈류 변화 반영)
        temps = np.array(self.forehead_temp_history[-20:])
        temp_std = np.std(temps)
        temp_mean = np.mean(temps)
        
        # 혈류가 좋으면 온도 변동이 적절하고, 평균 온도가 정상
        if temp_std < 0.3:
            return "low"  # 혈류 저하
        elif temp_std > 0.8:
            return "high"  # 혈류 과다 또는 스트레스
        else:
            return "normal"
    
    def _calculate_confidence(self) -> float:
        """측정 신뢰도 계산"""
        confidence_factors = []
        
        # 1. 데이터 양
        data_amount = min(1.0, len(self.temperature_history) / self.hr_analysis_window)
        confidence_factors.append(data_amount)
        
        # 2. 측정 시간
        if self.measurement_start_time:
            duration = time.time() - self.measurement_start_time
            duration_score = min(1.0, duration / self.min_measurement_duration)
            confidence_factors.append(duration_score)
        
        # 3. 온도 일관성
        if len(self.temperature_history) > 10:
            temps = np.array(self.temperature_history[-20:])
            consistency = 1.0 - min(1.0, np.std(temps) / 2.0)
            confidence_factors.append(consistency)
        
        if not confidence_factors:
            return 0.0
        
        return float(np.mean(confidence_factors))
    
    def _skewness(self, data: np.ndarray) -> float:
        """왜도 계산"""
        if len(data) < 3:
            return 0.0
        mean = np.mean(data)
        std = np.std(data)
        if std == 0:
            return 0.0
        return float(np.mean(((data - mean) / std) ** 3))
    
    def reset(self):
        """측정 상태 초기화"""
        self.temperature_history.clear()
        self.forehead_temp_history.clear()
        self.cheek_temp_history.clear()
        self.nose_temp_history.clear()
        self.timestamps.clear()
        self.measurement_start_time = None

