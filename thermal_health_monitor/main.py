"""
메인 애플리케이션
라즈베리파이5 + MLX9064X 열화상 카메라 기반 건강 모니터링 시스템

실행 방법:
    python -m thermal_health_monitor.main
    또는
    cd thermal_health_monitor && python main.py
"""

import sys
import time
import logging
import signal
import argparse
from pathlib import Path

# 프로젝트 루트를 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from thermal_health_monitor.camera import MLX9064XDriver, ThermalFrame
from thermal_health_monitor.face_detection import ThermalFaceDetector, FaceRegion
from thermal_health_monitor.health_analysis import HealthExtractor, HealthMetrics
from thermal_health_monitor.visualization import ThermalVisualizer
from thermal_health_monitor.data_storage import HealthDataLogger
from thermal_health_monitor.config import SystemConfig

# OpenCV는 시각화에 필요
try:
    import cv2
except ImportError:
    cv2 = None
    logger.warning("OpenCV not available. Display will be disabled.")

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ThermalHealthMonitor:
    """
    열화상 건강 모니터링 시스템 메인 클래스
    """
    
    def __init__(self, config: SystemConfig = None):
        """
        Args:
            config: 시스템 설정 객체
        """
        self.config = config or SystemConfig()
        self.running = False
        
        # 컴포넌트 초기화
        logger.info("Initializing system components...")
        
        # 카메라
        self.camera = MLX9064XDriver(
            i2c_frequency=self.config.camera.i2c_frequency,
            refresh_rate=self.config.camera.refresh_rate,
            resolution=self.config.camera.resolution,
            simulation_mode=self.config.camera.simulation_mode
        )
        
        # 얼굴 탐지
        self.face_detector = ThermalFaceDetector(
            min_face_temp=self.config.face_detection.min_face_temp,
            max_face_temp=self.config.face_detection.max_face_temp,
            min_face_size=self.config.face_detection.min_face_size,
            max_face_size=self.config.face_detection.max_face_size,
            aspect_ratio_range=self.config.face_detection.aspect_ratio_range,
            smoothing_window=self.config.face_detection.smoothing_window
        )
        
        # 건강 정보 추출
        self.health_extractor = HealthExtractor(
            sampling_rate=self.config.health_analysis.sampling_rate,
            hr_analysis_window=self.config.health_analysis.hr_analysis_window,
            rr_analysis_window=self.config.health_analysis.rr_analysis_window,
            min_measurement_duration=self.config.health_analysis.min_measurement_duration
        )
        
        # 시각화
        self.visualizer = ThermalVisualizer(
            display_width=self.config.visualization.display_width,
            display_height=self.config.visualization.display_height,
            colormap=self.config.visualization.colormap
        )
        
        # 데이터 저장
        self.data_logger = HealthDataLogger(
            data_dir=self.config.data_storage.data_dir,
            max_memory_records=self.config.data_storage.max_memory_records
        )
        
        # 통계
        self.frame_count = 0
        self.face_detected_count = 0
        self.last_health_metrics = None
        
        logger.info("System initialization complete")
    
    def run(self, display: bool = True, save_data: bool = True):
        """
        메인 루프 실행
        
        Args:
            display: 화면 표시 여부
            save_data: 데이터 저장 여부
        """
        self.running = True
        
        # 시그널 핸들러 등록 (Ctrl+C 처리)
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        logger.info("Starting health monitoring...")
        logger.info("Press Ctrl+C to stop")
        
        # 카메라 캘리브레이션
        if not self.config.camera.simulation_mode:
            self.camera.calibrate()
        
        try:
            while self.running:
                # 프레임 읽기
                frame = self.camera.read_frame()
                if frame is None:
                    logger.warning("Failed to read frame")
                    time.sleep(0.1)
                    continue
                
                self.frame_count += 1
                
                # 얼굴 탐지
                face_region = self.face_detector.detect(
                    frame.temperature_array,
                    frame.ambient_temperature
                )
                
                if face_region:
                    self.face_detected_count += 1
                    
                    # 건강 정보 추출을 위한 프레임 추가
                    self.health_extractor.add_frame(
                        frame.temperature_array,
                        face_region,
                        frame.timestamp
                    )
                    
                    # 건강 지표 추출
                    health_metrics = self.health_extractor.extract_health_metrics()
                    
                    if health_metrics:
                        self.last_health_metrics = health_metrics
                        
                        # 데이터 저장
                        if save_data:
                            self.data_logger.log(health_metrics)
                        
                        # 로그 출력 (주기적으로)
                        if self.frame_count % 16 == 0:  # 약 1초마다
                            self._log_health_status(health_metrics)
                else:
                    # 얼굴이 탐지되지 않으면 측정 초기화
                    if self.frame_count % 100 == 0:  # 100프레임마다 확인
                        self.health_extractor.reset()
                        self.face_detector.reset()
                
                # 시각화 및 표시
                if display and cv2 is not None:
                    image = self.visualizer.visualize_frame(
                        frame.temperature_array,
                        face_region,
                        self.last_health_metrics,
                        show_info=self.config.visualization.show_info
                    )
                    
                    cv2.imshow('Thermal Health Monitor', image)
                    
                    # 'q' 키로 종료
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        logger.info("Quit key pressed")
                        break
                
                # 프레임 레이트 제어
                time.sleep(1.0 / self.config.camera.refresh_rate)
        
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        except Exception as e:
            logger.error(f"Error in main loop: {e}", exc_info=True)
        finally:
            self.cleanup()
    
    def _log_health_status(self, metrics: HealthMetrics):
        """건강 상태 로그 출력"""
        status_parts = [
            f"Temp: {metrics.body_temperature:.2f}°C"
        ]
        
        if metrics.heart_rate:
            status_parts.append(f"HR: {metrics.heart_rate:.0f} bpm")
        
        if metrics.respiration_rate:
            status_parts.append(f"RR: {metrics.respiration_rate:.1f} /min")
        
        if metrics.stress_index is not None:
            status_parts.append(f"Stress: {metrics.stress_index:.2f}")
        
        if metrics.fever_detected:
            status_parts.append("[FEVER DETECTED]")
        
        logger.info(" | ".join(status_parts))
    
    def _signal_handler(self, signum, frame):
        """시그널 핸들러"""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
    
    def cleanup(self):
        """리소스 정리"""
        logger.info("Cleaning up resources...")
        
        # 카메라 종료
        self.camera.close()
        
        # OpenCV 창 닫기
        if cv2 is not None:
            cv2.destroyAllWindows()
        
        # 통계 출력
        logger.info(f"Total frames: {self.frame_count}")
        logger.info(f"Faces detected: {self.face_detected_count}")
        
        if self.face_detected_count > 0:
            detection_rate = self.face_detected_count / self.frame_count * 100
            logger.info(f"Face detection rate: {detection_rate:.1f}%")
        
        # 데이터 통계
        stats = self.data_logger.get_statistics()
        if stats:
            logger.info("Session statistics:")
            logger.info(f"  Total records: {stats['total_records']}")
            if stats['temperature']['mean']:
                logger.info(f"  Avg temperature: {stats['temperature']['mean']:.2f}°C")
            if stats['heart_rate']['mean']:
                logger.info(f"  Avg heart rate: {stats['heart_rate']['mean']:.0f} bpm")
        
        logger.info("Cleanup complete")


def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(
        description='Thermal Health Monitor - MLX9064X 기반 건강 모니터링 시스템'
    )
    parser.add_argument(
        '--simulation',
        action='store_true',
        help='시뮬레이션 모드 실행 (하드웨어 없이 테스트)'
    )
    parser.add_argument(
        '--no-display',
        action='store_true',
        help='화면 표시 비활성화'
    )
    parser.add_argument(
        '--no-save',
        action='store_true',
        help='데이터 저장 비활성화'
    )
    parser.add_argument(
        '--data-dir',
        type=str,
        default='health_data',
        help='데이터 저장 디렉토리 (기본값: health_data)'
    )
    
    args = parser.parse_args()
    
    # 설정 생성
    config = SystemConfig()
    config.camera.simulation_mode = args.simulation
    config.data_storage.data_dir = args.data_dir
    
    # OpenCV import (표시 모드일 때만)
    if not args.no_display:
        import cv2
    
    # 모니터 생성 및 실행
    monitor = ThermalHealthMonitor(config)
    monitor.run(display=not args.no_display, save_data=not args.no_save)


if __name__ == '__main__':
    main()

