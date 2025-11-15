# rPPG 품질 개선 가이드

## 품질(Q) 계산 방식

품질 점수는 다음 요소들로 계산됩니다:

```
Q = SNR 기반 신뢰도 × 모션 페널티 × 발한 페널티 × SNR 페널티
```

### 1. SNR 기반 신뢰도 (기본 품질)
```python
snr_final = 피크 파워 / (주변 잡음 + 1e-8)
conf = clip((snr_final - 1.2) / 3.2, 0.0, 1.0)
```
- **SNR ≥ 4.4**: 품질 1.0
- **SNR < 1.2**: 품질 0.0
- **SNR 1.2-4.4**: 선형 보간

### 2. 모션 페널티 (완화됨)
```python
motion_pen = clip(1.0 - (motion_level / (motion_px_warn * 1.5)), 0.7, 1.0)
```
- **기존**: `motion_level / 6.0`, 최소값 0.4
- **개선**: `motion_level / (6.0 * 1.5) = motion_level / 9.0`, 최소값 0.7
- **움직임 < 9px**: 페널티 없음 (기존 6px)
- **움직임 ≥ 9px**: 최대 30% 감소 (기존 60%)
- **효과**: 모션 페널티 영향 완화

### 3. 발한 페널티
```python
persp_pen = 0.6 if 발한_감지 else 1.0
```
- 발한 감지 시 40% 감소

### 4. SNR 하한 페널티
```python
if snr < snr_face_min: q *= 0.5
```
- SNR < `snr_face_min` (기본 1.5)인 ROI는 50% 추가 감소

### 실제 계산 예시

```python
# 예시: SNR 신뢰도 = 0.8, motion_level = 8px, 발한 없음, SNR = 1.6

# 1. 기본 품질
conf = 0.8

# 2. 모션 페널티 (motion_px_warn = 6.0)
motion_pen = clip(1.0 - (8.0 / (6.0 * 1.5)), 0.7, 1.0)
           = clip(1.0 - (8.0 / 9.0), 0.7, 1.0)
           = clip(0.111, 0.7, 1.0)
           = 0.7  # 기존에는 0.4였음

# 3. 발한 페널티
persp_pen = 1.0

# 4. 중간 품질
q_temp = 0.8 * 0.7 * 1.0 = 0.56

# 5. SNR 페널티 (SNR = 1.6 > 1.5이므로 적용 안 됨)
q_final = 0.56

# 기존 방식이었다면:
# motion_pen = clip(1.0 - (8.0 / 6.0), 0.4, 1.0) = 0.4
# q_final = 0.8 * 0.4 * 1.0 = 0.32
# 개선 효과: 0.56 / 0.32 = 1.75배 향상
```

## 품질이 낮은 주요 원인

### 1. 얼굴 인식 불안정 ⚠️
**증상**: bbox가 자주 바뀌거나 점프함
**원인**:
- 다른 열원 오인식
- 얼굴 각도/거리 변화
- 조명/환경 온도 변화

**해결책**:
```python
# Config에서 설정 조정
enable_kcf_tracking = True  # KCF 추적기 활성화 (더 안정적)
lost_tolerance = 30  # 증가 (기본 20)
search_expand = 0.6  # 감소 (기본 0.8, 더 좁은 영역 검색)
```

### 2. 랜드마크 검출 실패 ⚠️
**증상**: 고정 비율 ROI 사용 (랜드마크 기반 ROI 추출 실패)
**원인**:
- 열화상 이미지 해상도 낮음
- 얼굴이 너무 작거나 멀리 있음
- MediaPipe가 열화상 이미지에서 실패

**해결책**:
```python
# 랜드마크 검출 신뢰도 조정
landmark_min_detection_confidence = 0.3  # 낮춤 (기본 0.5)
landmark_min_tracking_confidence = 0.3  # 낮춤 (기본 0.5)

# 또는 랜드마크 비활성화하고 고정 비율 최적화
enable_face_landmarks = False
roi_dynamic_positioning = True  # 온도 분포 기반 동적 조정 활성화
```

### 3. 모션 보상 실패 ⚠️
**증상**: motion_level이 높음 (>6px)
**원인**:
- 머리 움직임이 많음
- 카메라 고정 불안정
- 얼굴 추적 불안정

**해결책**:
```python
# 모션 보상 설정 조정
enable_motion_compensation = True
mc_stride = 1  # 감소 (기본 2, 더 자주 보상)

# 모션 경고 임계값 증가
motion_px_warn = 10.0  # 증가 (기본 6.0, 더 관대하게)
```

### 4. SNR 낮음 ⚠️
**증상**: SNR < 1.5
**원인**:
- 신호가 약함 (얼굴이 멀리 있음)
- 잡음이 많음 (환경 온도 변화)
- ROI 위치가 부정확함

**해결책**:
```python
# SNR 기준 완화 (임시)
snr_face_min = 1.2  # 감소 (기본 1.5)

# ROI 패치 크기 증가 (신호 강조)
roi_patch_size = 8  # 증가 (기본 6)

# 중심 가중치 증가
roi_center_weight = 0.95  # 증가 (기본 0.9)
```

### 5. 얼굴과 카메라 거리/각도 문제 ⚠️
**증상**: 일관되게 낮은 품질
**원인**:
- 얼굴이 너무 멀리 있음 (신호 약함)
- 얼굴 각도가 비정상적 (측면 등)
- 카메라 해상도 부족

**해결책**:
- **거리**: 얼굴이 프레임의 15-30% 차지하도록 조정
- **각도**: 정면을 향하도록 안내
- **해상도**: Super-resolution 활성화
```python
enable_superres = True
superres_scale = 2  # 또는 3
```

## 즉시 적용 가능한 개선 설정

### 설정 1: 안정성 우선 (얼굴 인식 안정화)
```python
cfg = ThermalrPPGConfig(
    # 얼굴 인식 안정화
    enable_kcf_tracking=True,  # KCF 추적기 활성화
    lost_tolerance=30,  # 증가
    
    # 랜드마크 설정
    enable_face_landmarks=True,
    landmark_min_detection_confidence=0.3,  # 낮춤
    landmark_min_tracking_confidence=0.3,  # 낮춤
    
    # 모션 보상
    enable_motion_compensation=True,
    mc_stride=1,  # 더 자주 보상
    motion_px_warn=10.0,  # 더 관대하게
)
```

### 설정 2: 신호 강화 (SNR 향상)
```python
cfg = ThermalrPPGConfig(
    # ROI 설정
    roi_patch_size=8,  # 증가
    roi_center_weight=0.95,  # 증가
    roi_use_weighted_mean=True,
    
    # SNR 기준 완화
    snr_face_min=1.2,  # 감소
    session_roi_quality_min=0.20,  # 감소 (기본 0.25)
    
    # Super-resolution
    enable_superres=True,
    superres_scale=2,
)
```

### 설정 3: 종합 최적화 (권장)
```python
cfg = ThermalrPPGConfig(
    # 얼굴 인식
    enable_kcf_tracking=True,
    lost_tolerance=25,
    
    # 랜드마크
    enable_face_landmarks=True,
    landmark_min_detection_confidence=0.4,
    landmark_min_tracking_confidence=0.4,
    
    # ROI
    roi_patch_size=7,
    roi_center_weight=0.92,
    roi_dynamic_positioning=True,
    
    # 모션
    enable_motion_compensation=True,
    mc_stride=1,
    motion_px_warn=8.0,
    
    # SNR
    snr_face_min=1.3,
    session_roi_quality_min=0.22,
    
    # Super-resolution
    enable_superres=True,
    superres_scale=2,
)
```

## 디버깅 방법

### 1. 로그 확인
```bash
# 품질 관련 로그 확인
grep "품질\|Quality\|SNR\|motion" 로그파일

# 주요 메시지:
# - "품질 기준 미달": Q < session_roi_quality_min
# - "SNR 하한 미달": SNR < snr_face_min
# - "Motion compensation 과도한 움직임": motion_level > 50
# - "랜드마크 기반 ROI 추출 실패": 랜드마크 검출 실패
```

### 2. 실시간 모니터링
- UI에서 "Quality q" 값 확인
- "Face" 상태 확인 (OK/LOST)
- "Track" 상태 확인 (OK/LOST)
- Motion level 확인

### 3. ROI 상태 확인
```python
# 로그에서 확인:
# - "랜드마크 기반 ROI 추출 성공": 랜드마크 사용 중
# - ROI별 SNR 값
# - ROI별 품질 값
```

## 체크리스트

### 환경 설정
- [ ] 얼굴이 프레임의 15-30% 차지
- [ ] 얼굴이 정면을 향함
- [ ] 주변 열원 최소화 (히터, 조명 등)
- [ ] 카메라 고정 안정적
- [ ] 환경 온도 안정적

### 설정 확인
- [ ] `enable_kcf_tracking = True` (안정성)
- [ ] `enable_motion_compensation = True` (움직임 보상)
- [ ] `enable_superres = True` (해상도 향상)
- [ ] `enable_face_landmarks = True` (정확한 ROI)
- [ ] `roi_patch_size >= 6` (신호 강조)

### 품질 임계값
- [ ] `session_roi_quality_min = 0.20-0.25` (적절한 수준)
- [ ] `snr_face_min = 1.2-1.5` (너무 높지 않게)
- [ ] `motion_px_warn = 8.0-10.0` (적절한 수준)

## 예상 품질 개선 효과

### 설정 1 (안정성 우선)
- **예상 Q 향상**: +0.1-0.2
- **안정성**: ⬆️⬆️
- **정확도**: ⬆️

### 설정 2 (신호 강화)
- **예상 Q 향상**: +0.15-0.25
- **안정성**: ⬆️
- **정확도**: ⬆️⬆️

### 설정 3 (종합 최적화)
- **예상 Q 향상**: +0.2-0.3
- **안정성**: ⬆️⬆️
- **정확도**: ⬆️⬆️

## 추가 개선 방안

### 1. 하드웨어 개선
- 더 높은 해상도 센서 사용
- 카메라 고정 장치 개선
- 온도 안정화 (에어컨 등)

### 2. 알고리즘 개선
- 다중 ROI 앙상블 가중치 최적화
- 칼만 필터 파라미터 튜닝
- 웨이블릿 노이즈 제거 강화

### 3. 데이터 수집
- 더 긴 측정 시간 (75초)
- 안정적인 자세 유지
- 환경 조건 최적화

