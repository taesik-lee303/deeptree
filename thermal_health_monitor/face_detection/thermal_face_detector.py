"""
열화상 이미지에서 얼굴을 탐지하는 모듈

열화상 이미지의 특성:
- 낮은 해상도 (보통 24x32 또는 12x16)
- 온도 정보만 포함
- 얼굴이 가장 따뜻한 영역 중 하나
"""

import logging
import numpy as np
import cv2
from typing import Optional, Tuple, List
from dataclasses import dataclass
from collections import deque

logger = logging.getLogger(__name__)


@dataclass
class FaceRegion:
    """탐지된 얼굴 영역 정보"""
    bbox: Tuple[int, int, int, int]  # (x, y, width, height)
    confidence: float  # 탐지 신뢰도
    forehead_center: Tuple[int, int]  # 이마 중심 좌표
    cheek_left: Tuple[int, int]  # 왼쪽 뺨 중심
    cheek_right: Tuple[int, int]  # 오른쪽 뺨 중심
    nose_tip: Tuple[int, int]  # 코 끝 좌표
    
    @property
    def center(self) -> Tuple[int, int]:
        """얼굴 중심 좌표"""
        x, y, w, h = self.bbox
        return (x + w // 2, y + h // 2)
    
    @property
    def area(self) -> int:
        """얼굴 영역 크기"""
        _, _, w, h = self.bbox
        return w * h


class ThermalFaceDetector:
    """
    열화상 이미지에서 얼굴을 탐지하는 클래스
    
    방법:
    1. 온도 임계값 기반 이진화
    2. 연결된 구성 요소 분석
    3. 얼굴 모양 특징 검증 (타원형, 크기, 위치)
    4. 얼굴 랜드마크 추정
    """
    
    def __init__(
        self,
        min_face_temp: float = 30.0,  # 최소 얼굴 온도 (Celsius)
        max_face_temp: float = 42.0,  # 최대 얼굴 온도
        min_face_size: int = 20,  # 최소 얼굴 픽셀 수
        max_face_size: int = 500,  # 최대 얼굴 픽셀 수
        aspect_ratio_range: Tuple[float, float] = (0.6, 1.5),  # 가로/세로 비율 범위
        smoothing_window: int = 5  # 얼굴 위치 평활화 윈도우 크기
    ):
        """
        Args:
            min_face_temp: 얼굴로 인식할 최소 온도
            max_face_temp: 얼굴로 인식할 최대 온도
            min_face_size: 얼굴 영역 최소 크기 (픽셀)
            max_face_size: 얼굴 영역 최대 크기 (픽셀)
            aspect_ratio_range: 얼굴 가로세로 비율 범위
            smoothing_window: 얼굴 위치 추적 평활화 윈도우
        """
        self.min_face_temp = min_face_temp
        self.max_face_temp = max_face_temp
        self.min_face_size = min_face_size
        self.max_face_size = max_face_size
        self.aspect_ratio_range = aspect_ratio_range
        self.smoothing_window = smoothing_window
        
        # 얼굴 위치 추적을 위한 큐
        self.face_history = deque(maxlen=smoothing_window)
        
    def detect(self, temperature_array: np.ndarray, ambient_temp: float) -> Optional[FaceRegion]:
        """
        열화상 이미지에서 얼굴 탐지
        
        Args:
            temperature_array: 온도 배열 (2D numpy array)
            ambient_temp: 주변 온도
            
        Returns:
            FaceRegion 객체 또는 None
        """
        h, w = temperature_array.shape
        
        # 1. 얼굴 온도 범위 필터링
        # 주변 온도보다 일정 이상 따뜻한 영역 찾기
        face_threshold = max(self.min_face_temp, ambient_temp + 8.0)
        face_mask = (temperature_array >= face_threshold) & (temperature_array <= self.max_face_temp)
        
        if not np.any(face_mask):
            return None
        
        # 2. 이진 이미지 생성
        binary = face_mask.astype(np.uint8) * 255
        
        # 3. 모폴로지 연산으로 노이즈 제거
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
        
        # 4. 연결된 구성 요소 찾기
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
        
        if num_labels < 2:  # 배경만 있음
            return None
        
        # 5. 가장 큰 구성 요소 찾기 (얼굴일 가능성 높음)
        # 배경(라벨 0) 제외
        candidate_indices = []
        for i in range(1, num_labels):
            area = stats[i, cv2.CC_STAT_AREA]
            if self.min_face_size <= area <= self.max_face_size:
                candidate_indices.append(i)
        
        if not candidate_indices:
            return None
        
        # 가장 큰 영역 선택
        best_idx = max(candidate_indices, key=lambda i: stats[i, cv2.CC_STAT_AREA])
        
        # 6. 얼굴 모양 검증
        x = stats[best_idx, cv2.CC_STAT_LEFT]
        y = stats[best_idx, cv2.CC_STAT_TOP]
        width = stats[best_idx, cv2.CC_STAT_WIDTH]
        height = stats[best_idx, cv2.CC_STAT_HEIGHT]
        
        aspect_ratio = width / height if height > 0 else 0
        
        if not (self.aspect_ratio_range[0] <= aspect_ratio <= self.aspect_ratio_range[1]):
            return None
        
        # 7. 얼굴 랜드마크 추정
        face_bbox = (x, y, width, height)
        landmarks = self._estimate_landmarks(temperature_array, face_bbox, labels == best_idx)
        
        # 8. 신뢰도 계산
        confidence = self._calculate_confidence(
            temperature_array, face_bbox, labels == best_idx, ambient_temp
        )
        
        face_region = FaceRegion(
            bbox=face_bbox,
            confidence=confidence,
            forehead_center=landmarks['forehead'],
            cheek_left=landmarks['cheek_left'],
            cheek_right=landmarks['cheek_right'],
            nose_tip=landmarks['nose']
        )
        
        # 9. 위치 평활화 (추적 안정화)
        self.face_history.append(face_region)
        smoothed_face = self._smooth_face_position()
        
        return smoothed_face if smoothed_face else face_region
    
    def _estimate_landmarks(
        self,
        temperature_array: np.ndarray,
        bbox: Tuple[int, int, int, int],
        face_mask: np.ndarray
    ) -> dict:
        """얼굴 랜드마크 추정"""
        x, y, w, h = bbox
        cx, cy = x + w // 2, y + h // 2
        
        # 얼굴 영역 내 온도 분포 분석
        face_region = temperature_array[y:y+h, x:x+w]
        face_mask_region = face_mask[y:y+h, x:x+w]
        
        # 이마: 상단 1/3 영역에서 가장 따뜻한 지점
        forehead_y = int(h * 0.15)
        forehead_region = face_region[:forehead_y, :]
        if np.any(forehead_region > 0):
            max_idx = np.unravel_index(np.argmax(forehead_region), forehead_region.shape)
            forehead = (x + max_idx[1], y + max_idx[0])
        else:
            forehead = (cx, y + int(h * 0.15))
        
        # 코 끝: 얼굴 중심, 중간 높이
        nose = (cx, cy)
        
        # 왼쪽 뺨: 좌측 1/3, 중간 높이
        cheek_left = (x + int(w * 0.25), cy)
        
        # 오른쪽 뺨: 우측 1/3, 중간 높이
        cheek_right = (x + int(w * 0.75), cy)
        
        return {
            'forehead': forehead,
            'nose': nose,
            'cheek_left': cheek_left,
            'cheek_right': cheek_right
        }
    
    def _calculate_confidence(
        self,
        temperature_array: np.ndarray,
        bbox: Tuple[int, int, int, int],
        face_mask: np.ndarray,
        ambient_temp: float
    ) -> float:
        """얼굴 탐지 신뢰도 계산"""
        x, y, w, h = bbox
        
        # 얼굴 영역 온도
        face_region = temperature_array[y:y+h, x:x+w]
        face_temps = face_region[face_mask[y:y+h, x:x+w]]
        
        if len(face_temps) == 0:
            return 0.0
        
        # 온도 차이 (얼굴이 주변보다 따뜻한 정도)
        temp_diff = np.mean(face_temps) - ambient_temp
        temp_score = min(1.0, temp_diff / 10.0)  # 10도 차이면 최고 점수
        
        # 온도 일관성 (얼굴 온도가 일정한 범위 내)
        temp_std = np.std(face_temps)
        consistency_score = max(0.0, 1.0 - temp_std / 2.0)  # 표준편차가 작을수록 좋음
        
        # 크기 점수 (적절한 크기)
        area = w * h
        size_score = 1.0 - abs(area - (self.min_face_size + self.max_face_size) / 2) / self.max_face_size
        
        # 종합 신뢰도
        confidence = (temp_score * 0.4 + consistency_score * 0.3 + size_score * 0.3)
        
        return float(np.clip(confidence, 0.0, 1.0))
    
    def _smooth_face_position(self) -> Optional[FaceRegion]:
        """얼굴 위치 평활화"""
        if len(self.face_history) < 2:
            return None
        
        # 최근 얼굴들의 평균 위치 계산
        recent_faces = list(self.face_history)
        
        # 바운딩 박스 평균
        avg_x = int(np.mean([f.bbox[0] for f in recent_faces]))
        avg_y = int(np.mean([f.bbox[1] for f in recent_faces]))
        avg_w = int(np.mean([f.bbox[2] for f in recent_faces]))
        avg_h = int(np.mean([f.bbox[3] for f in recent_faces]))
        
        # 랜드마크 평균
        avg_forehead = (
            int(np.mean([f.forehead_center[0] for f in recent_faces])),
            int(np.mean([f.forehead_center[1] for f in recent_faces]))
        )
        avg_nose = (
            int(np.mean([f.nose_tip[0] for f in recent_faces])),
            int(np.mean([f.nose_tip[1] for f in recent_faces]))
        )
        avg_cheek_l = (
            int(np.mean([f.cheek_left[0] for f in recent_faces])),
            int(np.mean([f.cheek_left[1] for f in recent_faces]))
        )
        avg_cheek_r = (
            int(np.mean([f.cheek_right[0] for f in recent_faces])),
            int(np.mean([f.cheek_right[1] for f in recent_faces]))
        )
        
        # 평균 신뢰도
        avg_confidence = np.mean([f.confidence for f in recent_faces])
        
        return FaceRegion(
            bbox=(avg_x, avg_y, avg_w, avg_h),
            confidence=float(avg_confidence),
            forehead_center=avg_forehead,
            cheek_left=avg_cheek_l,
            cheek_right=avg_cheek_r,
            nose_tip=avg_nose
        )
    
    def reset(self):
        """탐지 상태 초기화"""
        self.face_history.clear()

