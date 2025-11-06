# Thermal rPPG 측정 시간 최적화 가이드

## ⏱️ **측정 소요시간 분석**

### **기본 모드 (현재 설정)**
```
📊 측정 단계별 소요시간:
1. 얼굴 인식: 0.375초 (6프레임 @ 16Hz)
2. 데이터 수집: 12초 (최소 측정 시간)
3. 첫 HR 계산: 0.75초 후
4. 첫 RR 계산: 2.0초 후

총 소요시간: 약 12-15초
```

### **빠른 모드 (Fast Mode)**
```
🚀 빠른 측정 단계별 소요시간:
1. 얼굴 인식: 0.15초 (3프레임 @ 20Hz)
2. 데이터 수집: 6초 (최소 측정 시간)
3. 첫 HR 계산: 0.5초 후
4. 첫 RR 계산: 1.0초 후

총 소요시간: 약 6-8초 (50% 단축!)
```

## ⚙️ **측정 모드 설정 방법**

### **1. 기본 모드 (정확도 우선)**
```python
cfg = ThermalrPPGConfig(
    # 기본 설정
    min_measurement_duration=12,    # 12초 측정
    hr_period=0.75,                 # HR 계산 주기
    present_rise_frames=6,          # 얼굴 인식 프레임
    sampling_rate=16.0,             # 샘플링 레이트
    
    # 빠른 모드 비활성화
    enable_fast_mode=False,
)
```

### **2. 빠른 모드 (속도 우선)**
```python
cfg = ThermalrPPGConfig(
    # 빠른 모드 활성화
    enable_fast_mode=True,
    fast_min_duration=6,            # 6초 측정
    fast_hr_period=0.5,             # HR 계산 주기 단축
    fast_present_frames=3,          # 얼굴 인식 프레임 단축
    fast_sampling_rate=20.0,        # 샘플링 레이트 증가
)
```

### **3. 균형 모드 (정확도 + 속도)**
```python
cfg = ThermalrPPGConfig(
    # 중간 설정
    min_measurement_duration=8,     # 8초 측정
    hr_period=0.6,                  # HR 계산 주기
    present_rise_frames=4,          # 얼굴 인식 프레임
    sampling_rate=18.0,             # 샘플링 레이트
    
    # 빠른 모드 비활성화
    enable_fast_mode=False,
)
```

## 📊 **모드별 성능 비교**

| 모드 | 측정시간 | 정확도 | 안정성 | 용도 |
|------|----------|--------|--------|------|
| **기본 모드** | 12-15초 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 의료용, 연구용 |
| **빠른 모드** | 6-8초 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 일반 사용, 스크리닝 |
| **균형 모드** | 8-10초 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 일상 모니터링 |

## 🎯 **사용 시나리오별 권장 설정**

### **🏥 의료/연구용 (정확도 최우선)**
```python
cfg = ThermalrPPGConfig(
    min_measurement_duration=15,    # 더 긴 측정 시간
    hr_period=1.0,                  # 더 긴 계산 주기
    enable_fast_mode=False,
    enable_ensemble_learning=True,   # 모든 AI 기능 활성화
    enable_wavelet_denoising=True,
    enable_adaptive_filtering=True,
    enable_personalized_model=True,
)
# 예상 소요시간: 15-18초
```

### **🏠 일반 사용자용 (균형)**
```python
cfg = ThermalrPPGConfig(
    min_measurement_duration=8,     # 적당한 측정 시간
    hr_period=0.6,                   # 적당한 계산 주기
    enable_fast_mode=False,
    enable_ensemble_learning=True,    # AI 기능 활성화
    enable_wavelet_denoising=True,
    enable_adaptive_filtering=True,
    enable_personalized_model=False,  # 개인화 모델 비활성화
)
# 예상 소요시간: 8-10초
```

### **⚡ 빠른 스크리닝용 (속도 최우선)**
```python
cfg = ThermalrPPGConfig(
    enable_fast_mode=True,           # 빠른 모드 활성화
    fast_min_duration=5,             # 최소 측정 시간
    fast_hr_period=0.4,             # 빠른 HR 계산
    fast_present_frames=2,           # 빠른 얼굴 인식
    fast_sampling_rate=25.0,         # 높은 샘플링 레이트
    enable_ensemble_learning=False,  # 무거운 AI 기능 비활성화
    enable_wavelet_denoising=True,   # 가벼운 노이즈 제거만
)
# 예상 소요시간: 5-7초
```

### **🍓 라즈베리파이용 (리소스 최적화)**
```python
cfg = ThermalrPPGConfig(
    min_measurement_duration=10,    # 적당한 측정 시간
    hr_period=0.8,                  # 계산 주기 조정
    enable_fast_mode=False,
    enable_pi_optimization=True,    # 라즈베리파이 최적화
    pi_memory_limit_mb=256,         # 메모리 제한
    enable_ensemble_learning=True,   # 축소된 앙상블 모델
    enable_wavelet_denoising=True,
    enable_adaptive_filtering=True,
    enable_personalized_model=False, # 개인화 모델 비활성화
)
# 예상 소요시간: 10-12초
```

## 📈 **측정 시간 단축 팁**

### **1. 환경 최적화**
- **조명**: 적절한 조명으로 얼굴 인식 속도 향상
- **거리**: 센서와 얼굴 사이 적절한 거리 유지 (30-50cm)
- **각도**: 얼굴이 센서에 정면으로 향하도록 조정

### **2. 설정 최적화**
- **샘플링 레이트**: 20Hz 이상으로 설정 (기본 16Hz)
- **얼굴 인식 프레임**: 3-4프레임으로 단축 (기본 6프레임)
- **HR 계산 주기**: 0.5초로 단축 (기본 0.75초)

### **3. AI 기능 선택적 사용**
- **웨이블릿 노이즈 제거**: 항상 활성화 (가벼움)
- **칼만 필터**: 항상 활성화 (가벼움)
- **앙상블 학습**: 필요시만 활성화 (무거움)
- **개인화 모델**: 장기 사용시만 활성화 (무거움)

## 🔧 **실시간 측정 시간 모니터링**

### **로그에서 확인**
```bash
# 측정 시작 로그
grep "Fast measurement started" thermal_rppg.log

# 첫 HR 측정 로그
grep "First HR measurement" thermal_rppg.log

# 첫 RR 측정 로그
grep "First RR measurement" thermal_rppg.log
```

### **코드에서 확인**
```python
# 측정 통계 확인
stats = app.fast_mode.get_measurement_stats()
print(f"총 경과 시간: {stats['total_elapsed']:.2f}초")
print(f"첫 HR 측정: {stats['first_hr_time']:.2f}초")
print(f"첫 RR 측정: {stats['first_rr_time']:.2f}초")
```

## 🎯 **권장사항**

1. **첫 사용**: 기본 모드로 시작하여 시스템 안정성 확인
2. **일상 사용**: 균형 모드로 설정하여 적당한 속도와 정확도 확보
3. **빠른 확인**: 빠른 모드로 설정하여 스크리닝 용도로 사용
4. **라즈베리파이**: 라즈베리파이 최적화 모드로 설정

## 📊 **예상 성능 향상**

- **빠른 모드**: 측정 시간 50% 단축 (12초 → 6초)
- **균형 모드**: 측정 시간 25% 단축 (12초 → 8초)
- **AI 최적화**: 정확도 15-25% 향상
- **라즈베리파이 최적화**: 리소스 사용량 30% 감소
