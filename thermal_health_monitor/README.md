# Thermal Health Monitor System

라즈베리파이5와 MLX9064X 열화상 카메라를 이용한 얼굴 탐지 및 건강 정보 추출 시스템

## 개요

이 시스템은 MLX9064X 열화상 카메라를 사용하여 비접촉 방식으로 사용자의 건강 정보를 모니터링합니다.

### 주요 기능

1. **얼굴 탐지**: 열화상 이미지에서 얼굴 영역 자동 탐지
2. **체온 측정**: 이마 온도를 기반으로 체온 추정
3. **심박수 측정**: 열화상 rPPG (remote photoplethysmography) 기법 사용
4. **호흡수 측정**: 코/입 주변 온도 변화 분석
5. **스트레스 지수**: 얼굴 온도 분포 및 변동성 분석
6. **혈류 상태**: 얼굴 온도 변동을 통한 혈류 상태 추정
7. **실시간 시각화**: 열화상 이미지와 건강 정보를 실시간으로 표시
8. **데이터 저장**: JSON 및 CSV 형식으로 건강 데이터 저장

## 시스템 요구사항

### 하드웨어

- 라즈베리파이 5
- MLX9064X 열화상 카메라 (I2C 인터페이스)
- 디스플레이 (선택사항, 시각화용)

### 소프트웨어

- Python 3.8 이상
- 라즈베리파이 OS (또는 호환 리눅스 배포판)
- I2C 활성화 (라즈베리파이 설정에서)

## 설치

### 1. 시스템 패키지 설치

```bash
sudo apt-get update
sudo apt-get install -y python3-pip python3-dev python3-numpy
sudo apt-get install -y i2c-tools
```

### 2. I2C 활성화

```bash
sudo raspi-config
# Interface Options > I2C > Enable
```

### 3. Python 패키지 설치

```bash
cd thermal_health_monitor
pip3 install -r requirements.txt
```

### 4. MLX9064X 드라이버 설치

MLX9064X는 MLX90640/90641과 유사한 인터페이스를 가질 것으로 예상됩니다.

```bash
# Adafruit CircuitPython 라이브러리 설치
pip3 install adafruit-circuitpython-mlx90640
# 또는
pip3 install adafruit-circuitpython-mlx90641

# I2C 지원 라이브러리
pip3 install adafruit-blinka
```

## 사용 방법

### 기본 실행

```bash
python3 -m thermal_health_monitor.main
```

### 시뮬레이션 모드 (하드웨어 없이 테스트)

```bash
python3 -m thermal_health_monitor.main --simulation
```

### 화면 표시 없이 실행

```bash
python3 -m thermal_health_monitor.main --no-display
```

### 데이터 저장 비활성화

```bash
python3 -m thermal_health_monitor.main --no-save
```

### 커스텀 데이터 디렉토리

```bash
python3 -m thermal_health_monitor.main --data-dir /path/to/data
```

## 시스템 아키텍처

```
thermal_health_monitor/
├── camera/              # MLX9064X 카메라 드라이버
│   ├── __init__.py
│   └── mlx9064x_driver.py
├── face_detection/      # 얼굴 탐지 모듈
│   ├── __init__.py
│   └── thermal_face_detector.py
├── health_analysis/     # 건강 정보 추출 모듈
│   ├── __init__.py
│   └── health_extractor.py
├── visualization/       # 시각화 모듈
│   ├── __init__.py
│   └── thermal_visualizer.py
├── data_storage/        # 데이터 저장 모듈
│   ├── __init__.py
│   └── health_data_logger.py
├── config.py           # 설정 파일
├── main.py             # 메인 애플리케이션
├── requirements.txt    # 의존성 목록
└── README.md           # 이 파일
```

## 작동 원리

### 1. 열화상 이미지 획득

MLX9064X 카메라가 I2C 인터페이스를 통해 열화상 데이터를 읽어옵니다. 해상도는 일반적으로 24x32 또는 16x12 픽셀입니다.

### 2. 얼굴 탐지

열화상 이미지에서 주변 온도보다 일정 이상 따뜻한 영역을 찾아 얼굴로 인식합니다. 온도 임계값, 크기, 형태 등을 종합적으로 분석합니다.

### 3. 건강 정보 추출

- **체온**: 이마 영역의 평균 온도를 측정하여 체온으로 추정
- **심박수**: 이마 온도의 미세한 변동을 FFT 분석하여 심박 주파수 추출
- **호흡수**: 코 주변 온도 변화를 분석하여 호흡 주파수 추출
- **스트레스 지수**: 얼굴 온도 분포의 변동성과 비대칭성 분석
- **혈류 상태**: 온도 변동 패턴을 통해 혈류 상태 추정

### 4. 시각화 및 저장

실시간으로 열화상 이미지와 건강 정보를 표시하고, JSON/CSV 형식으로 데이터를 저장합니다.

## 데이터 형식

### JSON 형식

```json
{
  "records": [
    {
      "timestamp": 1234567890.123,
      "body_temperature": 36.5,
      "heart_rate": 72.0,
      "respiration_rate": 16.5,
      "stress_index": 0.3,
      "blood_flow_status": "normal",
      "fever_detected": false,
      "confidence": 0.85
    }
  ]
}
```

### CSV 형식

CSV 파일은 스프레드시트 프로그램에서 바로 열어볼 수 있습니다.

## 주의사항

1. **의료 기기 아님**: 이 시스템은 의료 기기가 아니며, 진단 목적으로 사용할 수 없습니다.
2. **정확도**: 측정 정확도는 환경 조건, 센서 위치, 사용자 상태 등에 따라 달라질 수 있습니다.
3. **캘리브레이션**: 정확한 측정을 위해 주기적인 캘리브레이션이 필요할 수 있습니다.
4. **개인정보**: 건강 데이터는 민감한 개인정보이므로 적절히 보호해야 합니다.

## 문제 해결

### 카메라가 감지되지 않음

```bash
# I2C 장치 확인
sudo i2cdetect -y 1

# I2C 활성화 확인
lsmod | grep i2c
```

### 권한 오류

```bash
# 사용자를 i2c 그룹에 추가
sudo usermod -a -G i2c $USER
# 로그아웃 후 다시 로그인
```

### 성능 문제

- 해상도나 새로고침 주파수를 낮춰보세요
- 불필요한 시각화를 비활성화하세요 (`--no-display`)

## 라이선스

이 프로젝트는 교육 및 연구 목적으로 제공됩니다.

## 참고 자료

- [MLX9064X 데이터시트](https://www.melexis.com/)
- [Adafruit CircuitPython MLX90640 가이드](https://learn.adafruit.com/adafruit-mlx90640-thermal-camera)
- [열화상 rPPG 논문](https://ieeexplore.ieee.org/)

## 기여

버그 리포트나 기능 제안은 이슈로 등록해주세요.

