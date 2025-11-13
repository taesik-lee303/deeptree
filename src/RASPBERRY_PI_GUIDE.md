# 라즈베리파이5용 Thermal rPPG AI Enhancement 설치 가이드

## 🍓 **라즈베리파이5 호환성**

### **사양 요구사항**
- **라즈베리파이5**: 4GB RAM 이상 권장 (8GB 최적)
- **OS**: Raspberry Pi OS 64-bit (Bullseye 이상)
- **Python**: 3.9 이상
- **저장공간**: 최소 2GB 여유공간

### **성능 최적화 사항**
- ✅ **메모리 사용량**: 기본 512MB로 제한
- ✅ **CPU 부하**: 멀티스레딩 최적화
- ✅ **모델 크기**: 앙상블 모델 축소 (50→20 트리)
- ✅ **히스토리 크기**: 데이터 버퍼 축소 (1000→200)
- ✅ **자동 감지**: 라즈베리파이 자동 감지 및 최적화

## 📦 **설치 방법**

### **1단계: 시스템 업데이트**
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3-pip python3-venv -y
```

### **2단계: 필수 라이브러리 설치**
```bash
# NumPy/SciPy 최적화를 위한 BLAS 라이브러리
sudo apt install libopenblas-dev liblapack-dev -y

# 웨이블릿 변환용 라이브러리
sudo apt install python3-pywt -y

# 시스템 모니터링용
sudo apt install python3-psutil -y
```

### **3단계: Python 패키지 설치**
```bash
# 가상환경 생성 (권장)
python3 -m venv rppg_env
source rppg_env/bin/activate

# 라즈베리파이 최적화된 패키지 설치
pip install --no-cache-dir -r requirements_pi.txt

# 또는 개별 설치
pip install numpy==1.24.3 scipy==1.10.1 scikit-learn==1.2.2 PyWavelets==1.3.0 psutil==5.9.0
```

### **4단계: MLX 센서 라이브러리 설치**
```bash
# MLX90640/90641 센서용 라이브러리
pip install adafruit-circuitpython-mlx90640 adafruit-circuitpython-mlx90641
pip install adafruit-blinka
```

## ⚙️ **라즈베리파이 최적화 설정**

### **자동 최적화 (권장)**
```python
cfg = ThermalrPPGConfig(
    # 기본 설정들...
    
    # 라즈베리파이 최적화 (자동 감지)
    enable_pi_optimization=True,
    pi_memory_limit_mb=512,      # 메모리 사용량 제한
    pi_cpu_throttle=True,        # CPU 부하 제한
    pi_reduced_precision=True,   # 정밀도 감소로 성능 향상
)
```

### **수동 최적화 (고급 사용자)**
```python
# 메모리가 부족한 경우
cfg = ThermalrPPGConfig(
    enable_ensemble_learning=False,  # 가장 무거운 기능 비활성화
    enable_wavelet_denoising=True,   # 가벼운 기능만 유지
    enable_adaptive_filtering=True,
    enable_personalized_model=False,
    pi_memory_limit_mb=256,          # 메모리 제한 더 엄격하게
)

# CPU가 부족한 경우
cfg = ThermalrPPGConfig(
    sampling_rate=8.0,               # 샘플링 레이트 감소
    hr_period=1.5,                   # HR 계산 주기 증가
    rr_period=4.0,                   # RR 계산 주기 증가
    model_update_interval=600.0,     # 모델 업데이트 간격 증가
)
```

## 📊 **성능 모니터링**

### **리소스 사용량 확인**
```bash
# 메모리 사용량 확인
free -h

# CPU 사용량 확인
htop

# 프로세스별 메모리 사용량
ps aux --sort=-%mem | head -10
```

### **로그 모니터링**
```bash
# AI 최적화 로그 확인
grep "Raspberry Pi detected" thermal_rppg.log

# 메모리 경고 로그 확인
grep "High memory usage" thermal_rppg.log

# CPU 경고 로그 확인
grep "High CPU usage" thermal_rppg.log
```

## 🚀 **실행 방법**

### **기본 실행**
```bash
cd src
python -m modules.rppg.thermal_rppg
```

### **백그라운드 실행**
```bash
# systemd 서비스로 등록 (권장)
sudo cp thermal_rppg.service /etc/systemd/system/
sudo systemctl enable thermal_rppg
sudo systemctl start thermal_rppg

# 또는 nohup으로 실행
nohup python -m modules.rppg.thermal_rppg > rppg.log 2>&1 &
```

## 🔧 **문제 해결**

### **메모리 부족 오류**
```bash
# 스왑 파일 생성
sudo dphys-swapfile swapoff
sudo nano /etc/dphys-swapfile
# CONF_SWAPSIZE=1024  # 1GB 스왑
sudo dphys-swapfile setup
sudo dphys-swapfile swapon
```

### **CPU 과부하**
```bash
# CPU 클럭 속도 확인
vcgencmd measure_clock arm

# 온도 확인
vcgencmd measure_temp

# GPU 메모리 분할 조정
sudo raspi-config
# Advanced Options > Memory Split > 16
```

### **패키지 설치 오류**
```bash
# 컴파일러 설치
sudo apt install build-essential -y

# Python 개발 헤더 설치
sudo apt install python3-dev -y

# 다시 설치 시도
pip install --no-cache-dir --force-reinstall numpy scipy scikit-learn
```

## 📈 **예상 성능**

### **라즈베리파이5 4GB 기준**
- **메모리 사용량**: 200-400MB
- **CPU 사용률**: 30-60%
- **정확도**: 기존 대비 10-20% 향상
- **안정성**: 노이즈 환경에서 25-35% 개선

### **라즈베리파이5 8GB 기준**
- **메모리 사용량**: 300-600MB
- **CPU 사용률**: 20-50%
- **정확도**: 기존 대비 15-25% 향상
- **안정성**: 노이즈 환경에서 30-40% 개선

## 🎯 **최적화 팁**

1. **SSD 사용**: SD카드 대신 SSD 사용으로 I/O 성능 향상
2. **쿨링**: 적절한 쿨링으로 CPU 스로틀링 방지
3. **전원**: 안정적인 전원 공급 (5V 3A 이상)
4. **네트워크**: 유선 연결로 안정성 향상
5. **백그라운드**: 불필요한 서비스 비활성화

## 🔮 **향후 개선 계획**

- **TensorFlow Lite**: 모바일 최적화된 딥러닝 모델
- **ONNX Runtime**: 크로스 플랫폼 추론 엔진
- **OpenVINO**: Intel 최적화 추론 엔진
- **Edge TPU**: 구글 Edge TPU 활용 (라즈베리파이5 호환)

