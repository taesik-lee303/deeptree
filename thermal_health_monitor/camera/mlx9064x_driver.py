"""
MLX9064X 열화상 카메라 드라이버
라즈베리파이5에서 MLX9064X 센서를 제어하고 열화상 데이터를 읽어옵니다.
"""

import time
import logging
import numpy as np
from typing import Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# MLX9064X는 MLX90640/90641과 유사한 인터페이스를 가질 것으로 예상
# 실제 하드웨어가 없을 경우 시뮬레이션 모드 지원
try:
    import board
    import busio
    HAS_BOARD = True
except ImportError:
    HAS_BOARD = False
    logger.warning("board/busio not available. Using simulation mode.")

try:
    # MLX9064X는 아직 공식 라이브러리가 없을 수 있으므로
    # MLX90640/90641 라이브러리를 기반으로 확장 가능
    import adafruit_mlx90640 as mlx40
    HAS_MLX90640 = True
except ImportError:
    HAS_MLX90640 = False
    logger.warning("adafruit_mlx90640 not available. Using simulation mode.")

try:
    import adafruit_mlx90641 as mlx41
    HAS_MLX90641 = True
except ImportError:
    HAS_MLX90641 = False


@dataclass
class ThermalFrame:
    """열화상 프레임 데이터 클래스"""
    temperature_array: np.ndarray  # 온도 배열 (Celsius)
    timestamp: float  # 타임스탬프
    resolution: Tuple[int, int]  # 해상도 (height, width)
    ambient_temperature: float  # 주변 온도
    
    @property
    def min_temp(self) -> float:
        """최소 온도"""
        return float(np.min(self.temperature_array))
    
    @property
    def max_temp(self) -> float:
        """최대 온도"""
        return float(np.max(self.temperature_array))
    
    @property
    def mean_temp(self) -> float:
        """평균 온도"""
        return float(np.mean(self.temperature_array))
    
    def get_region_temp(self, y1: int, y2: int, x1: int, x2: int) -> float:
        """특정 영역의 평균 온도 반환"""
        region = self.temperature_array[y1:y2, x1:x2]
        return float(np.mean(region))


class MLX9064XDriver:
    """
    MLX9064X 열화상 카메라 드라이버
    
    MLX9064X는 32x24 또는 16x12 해상도를 가진 열화상 센서입니다.
    I2C 인터페이스를 통해 라즈베리파이와 통신합니다.
    """
    
    # MLX9064X 기본 설정 (실제 센서 사양에 맞게 조정 필요)
    DEFAULT_RESOLUTION = (24, 32)  # (height, width)
    DEFAULT_REFRESH_RATE = 16  # Hz
    DEFAULT_I2C_FREQ = 800_000  # 800kHz
    
    def __init__(
        self,
        i2c_frequency: int = DEFAULT_I2C_FREQ,
        refresh_rate: int = DEFAULT_REFRESH_RATE,
        resolution: Optional[Tuple[int, int]] = None,
        simulation_mode: bool = False
    ):
        """
        Args:
            i2c_frequency: I2C 통신 주파수 (Hz)
            refresh_rate: 센서 새로고침 주파수 (Hz)
            resolution: 센서 해상도 (height, width), None이면 자동 감지
            simulation_mode: 시뮬레이션 모드 활성화 (하드웨어 없이 테스트)
        """
        self.i2c_frequency = i2c_frequency
        self.refresh_rate = refresh_rate
        self.resolution = resolution or self.DEFAULT_RESOLUTION
        self.simulation_mode = simulation_mode
        
        self.i2c = None
        self.sensor = None
        self.is_initialized = False
        self.frame_interval = 1.0 / refresh_rate
        self.last_frame_time = 0.0
        
        # 시뮬레이션용 변수
        self.sim_frame_count = 0
        self.sim_base_temp = 36.5  # 시뮬레이션 기본 체온
        
        if not simulation_mode:
            self._initialize_hardware()
        else:
            logger.info("Running in simulation mode")
            self.is_initialized = True
    
    def _initialize_hardware(self):
        """하드웨어 초기화"""
        if not HAS_BOARD:
            logger.warning("Hardware libraries not available. Switching to simulation mode.")
            self.simulation_mode = True
            self.is_initialized = True
            return
        
        try:
            # I2C 버스 초기화
            self.i2c = busio.I2C(board.SCL, board.SDA, frequency=self.i2c_frequency)
            
            # MLX9064X는 아직 공식 라이브러리가 없을 수 있으므로
            # MLX90640/90641을 대체로 사용하거나 직접 I2C 통신 구현
            # 여기서는 MLX90640을 기본으로 사용 (유사한 인터페이스)
            if HAS_MLX90640:
                self.sensor = mlx40.MLX90640(self.i2c)
                try:
                    # 새로고침 주파수 설정
                    self.sensor.refresh_rate = mlx40.RefreshRate.REFRESH_16_HZ
                    self.refresh_rate = 16
                    self.frame_interval = 1.0 / 16
                    self.resolution = (24, 32)
                except Exception as e:
                    logger.warning(f"Could not set refresh rate: {e}")
            
            # 센서 안정화 대기
            time.sleep(2.0)
            
            logger.info(
                f"MLX9064X initialized successfully. "
                f"Resolution: {self.resolution}, Refresh rate: {self.refresh_rate}Hz"
            )
            self.is_initialized = True
            
        except Exception as e:
            logger.error(f"Failed to initialize MLX9064X: {e}")
            logger.info("Switching to simulation mode")
            self.simulation_mode = True
            self.is_initialized = True
    
    def read_frame(self) -> Optional[ThermalFrame]:
        """
        열화상 프레임 읽기
        
        Returns:
            ThermalFrame 객체 또는 None (읽기 실패 시)
        """
        if not self.is_initialized:
            logger.error("Camera not initialized")
            return None
        
        current_time = time.time()
        
        # 프레임 간격 제어
        if current_time - self.last_frame_time < self.frame_interval:
            time.sleep(self.frame_interval - (current_time - self.last_frame_time))
        
        self.last_frame_time = time.time()
        
        if self.simulation_mode:
            return self._read_simulation_frame()
        else:
            return self._read_hardware_frame()
    
    def _read_hardware_frame(self) -> Optional[ThermalFrame]:
        """하드웨어에서 프레임 읽기"""
        try:
            if self.sensor is None:
                return None
            
            # 센서에서 온도 배열 읽기
            frame_data = np.zeros(self.resolution[0] * self.resolution[1], dtype=np.float32)
            self.sensor.getFrame(frame_data)
            
            # 2D 배열로 변환
            temperature_array = frame_data.reshape(self.resolution)
            
            # 주변 온도 추정 (프레임 가장자리 평균)
            ambient = np.mean(np.concatenate([
                temperature_array[0, :],  # 상단
                temperature_array[-1, :],  # 하단
                temperature_array[:, 0],  # 좌측
                temperature_array[:, -1]  # 우측
            ]))
            
            return ThermalFrame(
                temperature_array=temperature_array,
                timestamp=time.time(),
                resolution=self.resolution,
                ambient_temperature=float(ambient)
            )
            
        except Exception as e:
            logger.error(f"Error reading frame from hardware: {e}")
            return None
    
    def _read_simulation_frame(self) -> ThermalFrame:
        """시뮬레이션 프레임 생성"""
        self.sim_frame_count += 1
        
        # 시뮬레이션: 얼굴 모양의 온도 분포 생성
        h, w = self.resolution
        temperature_array = np.zeros((h, w), dtype=np.float32)
        
        # 기본 주변 온도
        ambient = 22.0 + np.random.normal(0, 0.5)
        
        # 얼굴 영역 시뮬레이션 (타원형)
        center_y, center_x = h // 2, w // 2
        radius_y, radius_x = h // 3, w // 3
        
        for y in range(h):
            for x in range(w):
                dy = (y - center_y) / radius_y
                dx = (x - center_x) / radius_x
                dist = np.sqrt(dy**2 + dx**2)
                
                if dist < 1.0:
                    # 얼굴 영역: 체온 + 변동
                    temp = self.sim_base_temp + np.random.normal(0, 0.3)
                    # 이마 영역은 더 따뜻함
                    if y < center_y and abs(x - center_x) < radius_x * 0.5:
                        temp += 0.5
                    temperature_array[y, x] = temp
                else:
                    # 배경: 주변 온도
                    temperature_array[y, x] = ambient + np.random.normal(0, 0.2)
        
        # 시간에 따른 미세한 변동 (심박수 시뮬레이션)
        heartbeat = 0.1 * np.sin(2 * np.pi * 1.2 * self.sim_frame_count / self.refresh_rate)
        face_mask = temperature_array > ambient + 5
        temperature_array[face_mask] += heartbeat
        
        return ThermalFrame(
            temperature_array=temperature_array,
            timestamp=time.time(),
            resolution=self.resolution,
            ambient_temperature=ambient
        )
    
    def calibrate(self, num_samples: int = 10) -> bool:
        """
        센서 캘리브레이션
        
        Args:
            num_samples: 캘리브레이션에 사용할 샘플 수
            
        Returns:
            캘리브레이션 성공 여부
        """
        logger.info(f"Calibrating sensor with {num_samples} samples...")
        
        samples = []
        for _ in range(num_samples):
            frame = self.read_frame()
            if frame:
                samples.append(frame.ambient_temperature)
            time.sleep(0.1)
        
        if len(samples) < num_samples // 2:
            logger.warning("Calibration failed: insufficient samples")
            return False
        
        logger.info(f"Calibration complete. Ambient temperature: {np.mean(samples):.2f}°C")
        return True
    
    def close(self):
        """리소스 정리"""
        if self.i2c:
            try:
                self.i2c.deinit()
            except:
                pass
        self.is_initialized = False
        logger.info("Camera driver closed")

