"""
시스템 설정 파일
"""

from dataclasses import dataclass
from typing import Tuple


@dataclass
class CameraConfig:
    """카메라 설정"""
    i2c_frequency: int = 800_000  # I2C 주파수 (Hz)
    refresh_rate: int = 16  # 새로고침 주파수 (Hz)
    resolution: Tuple[int, int] = (24, 32)  # 해상도 (height, width)
    simulation_mode: bool = False  # 시뮬레이션 모드


@dataclass
class FaceDetectionConfig:
    """얼굴 탐지 설정"""
    min_face_temp: float = 30.0  # 최소 얼굴 온도 (Celsius)
    max_face_temp: float = 42.0  # 최대 얼굴 온도
    min_face_size: int = 20  # 최소 얼굴 크기 (픽셀)
    max_face_size: int = 500  # 최대 얼굴 크기 (픽셀)
    aspect_ratio_range: Tuple[float, float] = (0.6, 1.5)  # 가로세로 비율 범위
    smoothing_window: int = 5  # 위치 평활화 윈도우


@dataclass
class HealthAnalysisConfig:
    """건강 분석 설정"""
    sampling_rate: float = 16.0  # 샘플링 주파수 (Hz)
    hr_analysis_window: int = 64  # 심박수 분석 윈도우 (프레임)
    rr_analysis_window: int = 128  # 호흡수 분석 윈도우 (프레임)
    min_measurement_duration: float = 8.0  # 최소 측정 시간 (초)


@dataclass
class VisualizationConfig:
    """시각화 설정"""
    display_width: int = 640  # 디스플레이 너비
    display_height: int = 480  # 디스플레이 높이
    colormap: int = 2  # OpenCV 컬러맵 (2 = COLORMAP_JET)
    show_info: bool = True  # 건강 정보 표시


@dataclass
class DataStorageConfig:
    """데이터 저장 설정"""
    data_dir: str = "health_data"  # 데이터 저장 디렉토리
    max_memory_records: int = 1000  # 메모리 최대 레코드 수


@dataclass
class SystemConfig:
    """전체 시스템 설정"""
    camera: CameraConfig = None
    face_detection: FaceDetectionConfig = None
    health_analysis: HealthAnalysisConfig = None
    visualization: VisualizationConfig = None
    data_storage: DataStorageConfig = None
    
    def __post_init__(self):
        """기본값 설정"""
        if self.camera is None:
            self.camera = CameraConfig()
        if self.face_detection is None:
            self.face_detection = FaceDetectionConfig()
        if self.health_analysis is None:
            self.health_analysis = HealthAnalysisConfig()
        if self.visualization is None:
            self.visualization = VisualizationConfig()
        if self.data_storage is None:
            self.data_storage = DataStorageConfig()

