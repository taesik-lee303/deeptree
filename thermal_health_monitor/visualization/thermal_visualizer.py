"""
열화상 이미지 및 건강 정보 시각화 모듈
"""

import logging
import numpy as np
import cv2
from typing import Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


class ThermalVisualizer:
    """
    열화상 이미지와 건강 정보를 시각화하는 클래스
    """
    
    def __init__(
        self,
        display_width: int = 640,
        display_height: int = 480,
        colormap: int = cv2.COLORMAP_JET
    ):
        """
        Args:
            display_width: 디스플레이 너비
            display_height: 디스플레이 높이
            colormap: OpenCV 컬러맵 (cv2.COLORMAP_JET, cv2.COLORMAP_HOT 등)
        """
        self.display_width = display_width
        self.display_height = display_height
        self.colormap = colormap
    
    def visualize_frame(
        self,
        temperature_array: np.ndarray,
        face_region=None,
        health_metrics=None,
        show_info: bool = True
    ) -> np.ndarray:
        """
        열화상 프레임 시각화
        
        Args:
            temperature_array: 온도 배열
            face_region: FaceRegion 객체 (선택)
            health_metrics: HealthMetrics 객체 (선택)
            show_info: 건강 정보 표시 여부
            
        Returns:
            시각화된 이미지 (BGR)
        """
        h, w = temperature_array.shape
        
        # 1. 온도를 0-255 범위로 정규화
        temp_min = np.min(temperature_array)
        temp_max = np.max(temperature_array)
        
        if temp_max > temp_min:
            normalized = ((temperature_array - temp_min) / (temp_max - temp_min) * 255).astype(np.uint8)
        else:
            normalized = np.zeros((h, w), dtype=np.uint8)
        
        # 2. 컬러맵 적용
        colored = cv2.applyColorMap(normalized, self.colormap)
        
        # 3. 해상도 확대 (디스플레이 크기로)
        scale_x = self.display_width / w
        scale_y = self.display_height / h
        scale = min(scale_x, scale_y)
        
        new_w = int(w * scale)
        new_h = int(h * scale)
        
        resized = cv2.resize(colored, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
        
        # 4. 캔버스 생성 (검은 배경)
        canvas = np.zeros((self.display_height, self.display_width, 3), dtype=np.uint8)
        
        # 중앙에 배치
        y_offset = (self.display_height - new_h) // 2
        x_offset = (self.display_width - new_w) // 2
        canvas[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = resized
        
        # 5. 얼굴 영역 표시
        if face_region:
            canvas = self._draw_face_region(canvas, face_region, scale, x_offset, y_offset)
        
        # 6. 건강 정보 오버레이
        if show_info and health_metrics:
            canvas = self._draw_health_info(canvas, health_metrics, temperature_array)
        
        # 7. 온도 범위 표시
        canvas = self._draw_temperature_scale(canvas, temp_min, temp_max)
        
        return canvas
    
    def _draw_face_region(
        self,
        canvas: np.ndarray,
        face_region,
        scale: float,
        x_offset: int,
        y_offset: int
    ) -> np.ndarray:
        """얼굴 영역 그리기"""
        x, y, w, h = face_region.bbox
        
        # 스케일 적용 및 오프셋 추가
        x_scaled = int(x * scale) + x_offset
        y_scaled = int(y * scale) + y_offset
        w_scaled = int(w * scale)
        h_scaled = int(h * scale)
        
        # 바운딩 박스
        cv2.rectangle(canvas, (x_scaled, y_scaled), 
                     (x_scaled + w_scaled, y_scaled + h_scaled), 
                     (0, 255, 0), 2)
        
        # 랜드마크 표시
        landmarks = [
            (face_region.forehead_center, (255, 0, 0), "Forehead"),
            (face_region.nose_tip, (0, 255, 255), "Nose"),
            (face_region.cheek_left, (255, 255, 0), "Cheek L"),
            (face_region.cheek_right, (255, 255, 0), "Cheek R")
        ]
        
        for (landmark_y, landmark_x), color, label in landmarks:
            px = int(landmark_x * scale) + x_offset
            py = int(landmark_y * scale) + y_offset
            cv2.circle(canvas, (px, py), 3, color, -1)
            cv2.putText(canvas, label, (px + 5, py), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.3, color, 1)
        
        return canvas
    
    def _draw_health_info(
        self,
        canvas: np.ndarray,
        health_metrics,
        temperature_array: np.ndarray
    ) -> np.ndarray:
        """건강 정보 오버레이"""
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.6
        thickness = 2
        line_height = 25
        
        # 배경 패널
        panel_height = 200
        panel = np.zeros((panel_height, 300, 3), dtype=np.uint8)
        panel[:] = (40, 40, 40)  # 어두운 회색 배경
        
        y_pos = 20
        
        # 제목
        cv2.putText(panel, "Health Metrics", (10, y_pos), 
                   font, 0.7, (255, 255, 255), 2)
        y_pos += line_height
        
        # 체온
        temp_color = (0, 255, 0) if not health_metrics.fever_detected else (0, 0, 255)
        temp_text = f"Temperature: {health_metrics.body_temperature:.2f}C"
        if health_metrics.fever_detected:
            temp_text += " [FEVER]"
        cv2.putText(panel, temp_text, (10, y_pos), 
                   font, font_scale, temp_color, thickness)
        y_pos += line_height
        
        # 심박수
        if health_metrics.heart_rate:
            hr_text = f"Heart Rate: {health_metrics.heart_rate:.0f} bpm"
            cv2.putText(panel, hr_text, (10, y_pos), 
                       font, font_scale, (255, 255, 255), thickness)
            y_pos += line_height
        
        # 호흡수
        if health_metrics.respiration_rate:
            rr_text = f"Respiration: {health_metrics.respiration_rate:.1f} /min"
            cv2.putText(panel, rr_text, (10, y_pos), 
                       font, font_scale, (255, 255, 255), thickness)
            y_pos += line_height
        
        # 스트레스 지수
        if health_metrics.stress_index is not None:
            stress_level = "High" if health_metrics.stress_index > 0.6 else \
                          "Medium" if health_metrics.stress_index > 0.3 else "Low"
            stress_color = (0, 0, 255) if health_metrics.stress_index > 0.6 else \
                          (0, 165, 255) if health_metrics.stress_index > 0.3 else (0, 255, 0)
            stress_text = f"Stress: {stress_level} ({health_metrics.stress_index:.2f})"
            cv2.putText(panel, stress_text, (10, y_pos), 
                       font, font_scale, stress_color, thickness)
            y_pos += line_height
        
        # 혈류 상태
        if health_metrics.blood_flow_status:
            flow_color = {"normal": (0, 255, 0), "low": (0, 165, 255), "high": (0, 0, 255)}.get(
                health_metrics.blood_flow_status, (255, 255, 255)
            )
            flow_text = f"Blood Flow: {health_metrics.blood_flow_status.upper()}"
            cv2.putText(panel, flow_text, (10, y_pos), 
                       font, font_scale, flow_color, thickness)
            y_pos += line_height
        
        # 신뢰도
        conf_text = f"Confidence: {health_metrics.confidence:.0%}"
        conf_color = (0, 255, 0) if health_metrics.confidence > 0.7 else \
                    (0, 165, 255) if health_metrics.confidence > 0.4 else (0, 0, 255)
        cv2.putText(panel, conf_text, (10, y_pos), 
                   font, font_scale, conf_color, thickness)
        
        # 패널을 캔버스에 배치 (우측 상단)
        panel_y = 10
        panel_x = canvas.shape[1] - panel.shape[1] - 10
        canvas[panel_y:panel_y+panel_height, panel_x:panel_x+panel.shape[1]] = panel
        
        return canvas
    
    def _draw_temperature_scale(
        self,
        canvas: np.ndarray,
        temp_min: float,
        temp_max: float
    ) -> np.ndarray:
        """온도 스케일 표시"""
        scale_width = 20
        scale_height = 200
        scale_x = 10
        scale_y = (canvas.shape[0] - scale_height) // 2
        
        # 컬러바 생성
        colorbar = np.zeros((scale_height, scale_width, 3), dtype=np.uint8)
        for i in range(scale_height):
            ratio = 1.0 - (i / scale_height)
            temp = temp_min + (temp_max - temp_min) * ratio
            normalized = int((temp - temp_min) / (temp_max - temp_min) * 255) if temp_max > temp_min else 0
            normalized = np.clip(normalized, 0, 255)
            color = cv2.applyColorMap(np.array([[normalized]], dtype=np.uint8), self.colormap)[0, 0]
            colorbar[i, :] = color
        
        canvas[scale_y:scale_y+scale_height, scale_x:scale_x+scale_width] = colorbar
        
        # 온도 레이블
        font = cv2.FONT_HERSHEY_SIMPLEX
        cv2.putText(canvas, f"{temp_max:.1f}C", (scale_x + scale_width + 5, scale_y + 10), 
                   font, 0.4, (255, 255, 255), 1)
        cv2.putText(canvas, f"{temp_min:.1f}C", (scale_x + scale_width + 5, scale_y + scale_height - 5), 
                   font, 0.4, (255, 255, 255), 1)
        
        return canvas

