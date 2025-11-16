"""
사용 예제
간단한 사용 방법을 보여주는 예제 코드
"""

import time
from thermal_health_monitor.camera import MLX9064XDriver
from thermal_health_monitor.face_detection import ThermalFaceDetector
from thermal_health_monitor.health_analysis import HealthExtractor
from thermal_health_monitor.config import SystemConfig

def example_basic_usage():
    """기본 사용 예제"""
    print("=== 기본 사용 예제 ===")
    
    # 설정 생성
    config = SystemConfig()
    config.camera.simulation_mode = True  # 시뮬레이션 모드
    
    # 카메라 초기화
    camera = MLX9064XDriver(
        refresh_rate=config.camera.refresh_rate,
        simulation_mode=config.camera.simulation_mode
    )
    
    # 얼굴 탐지기 초기화
    face_detector = ThermalFaceDetector(
        min_face_temp=config.face_detection.min_face_temp,
        max_face_temp=config.face_detection.max_face_temp
    )
    
    # 건강 정보 추출기 초기화
    health_extractor = HealthExtractor(
        sampling_rate=config.health_analysis.sampling_rate
    )
    
    print("시스템 초기화 완료. 프레임 읽기 시작...")
    
    # 몇 프레임 읽기
    for i in range(100):
        frame = camera.read_frame()
        if frame is None:
            continue
        
        # 얼굴 탐지
        face_region = face_detector.detect(
            frame.temperature_array,
            frame.ambient_temperature
        )
        
        if face_region:
            print(f"프레임 {i}: 얼굴 탐지됨 (신뢰도: {face_region.confidence:.2f})")
            
            # 건강 정보 추출을 위한 프레임 추가
            health_extractor.add_frame(
                frame.temperature_array,
                face_region,
                frame.timestamp
            )
            
            # 건강 지표 추출
            health_metrics = health_extractor.extract_health_metrics()
            
            if health_metrics:
                print(f"  체온: {health_metrics.body_temperature:.2f}°C")
                if health_metrics.heart_rate:
                    print(f"  심박수: {health_metrics.heart_rate:.0f} bpm")
                if health_metrics.respiration_rate:
                    print(f"  호흡수: {health_metrics.respiration_rate:.1f} /min")
        
        time.sleep(0.1)
    
    # 정리
    camera.close()
    print("예제 완료")


def example_custom_config():
    """커스텀 설정 예제"""
    print("=== 커스텀 설정 예제 ===")
    
    # 설정 생성 및 수정
    config = SystemConfig()
    
    # 카메라 설정
    config.camera.refresh_rate = 8  # 8Hz로 낮춤 (성능 향상)
    config.camera.simulation_mode = True
    
    # 얼굴 탐지 설정
    config.face_detection.min_face_temp = 32.0  # 더 낮은 온도에서도 탐지
    config.face_detection.smoothing_window = 10  # 더 많은 평활화
    
    # 건강 분석 설정
    config.health_analysis.min_measurement_duration = 5.0  # 더 빠른 측정
    
    print(f"카메라 새로고침 주파수: {config.camera.refresh_rate}Hz")
    print(f"최소 얼굴 온도: {config.face_detection.min_face_temp}°C")
    print(f"최소 측정 시간: {config.health_analysis.min_measurement_duration}초")
    
    # 모니터 생성 (실제로는 main.py에서 사용)
    from thermal_health_monitor.main import ThermalHealthMonitor
    monitor = ThermalHealthMonitor(config)
    
    print("커스텀 설정으로 모니터 생성 완료")
    print("실제 실행은 monitor.run()을 호출하세요")


if __name__ == '__main__':
    # 기본 사용 예제 실행
    example_basic_usage()
    
    print("\n")
    
    # 커스텀 설정 예제 실행
    example_custom_config()

