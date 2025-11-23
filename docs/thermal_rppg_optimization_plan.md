# Thermal rPPG 최적화 계획

## 현재 문제점 분석

### 1. 얼굴 탐지 중복 로직
- **KCF 추적기** (가장 빠름, 정확도 높음)
- **템플릿 매칭** (KCF 비활성화 시만 사용, 느림)
- **컴포넌트 스코어링** (전체 프레임 검색, 가장 느림)
- **타원형 패턴 검증** (여러 곳에서 중복 계산)

**문제**: 실패할 때마다 다음 단계로 넘어가면서 전체 프레임 검색까지 진행
**해결**: KCF만 사용하거나, KCF 실패 시 로컬 영역 컴포넌트 스코어링만

### 2. ROI 추출 중복 로직
- **랜드마크 기반** (MediaPipe, 느림, 정확도 높음)
- **고정 비율** (빠름, 정확도 낮음)
- **동적 위치 조정** (매번 얼굴 중심 계산)

**문제**: 랜드마크 실패 시에도 매번 시도, 얼굴 중심 계산 반복
**해결**: 랜드마크는 주기적으로만 시도 (예: 10프레임마다), 실패 시 고정 비율 사용

### 3. 타원형 패턴 검증 중복
- `_score_components`에서 간단한 버전 계산
- `_check_elliptical_pattern`에서 상세 버전 계산
- `_validate_face_temperature`에서도 호출

**문제**: 같은 ROI에 대해 여러 번 계산
**해결**: 한 번만 계산하고 결과 캐싱

### 4. 전처리 중복
- `_preprocess_frame`이 여러 곳에서 호출
- 정규화, CLAHE, Bilateral Filter 반복

**문제**: 같은 프레임에 대해 여러 번 전처리
**해결**: 전처리 결과 캐싱 (bbox가 변하지 않으면 재사용)

### 5. 과도한 로깅
- 주기적 로깅이 너무 많음 (3초, 5초, 10초마다)
- 디버깅 정보 수집이 매 프레임마다

**문제**: 로깅 오버헤드
**해결**: 로깅 최소화, 에러/경고만 로깅

### 6. 신호 처리 중복
- 여러 ROI에서 동일한 FFT 계산
- 웨이블릿 노이즈 제거가 각 ROI마다

**문제**: 불필요한 계산 반복
**해결**: 이미 최적화되어 있음 (각 ROI는 독립적이므로 필요)

## 최적화 방안

### 우선순위 1: 얼굴 탐지 단순화
```python
def detect(self, frame: np.ndarray):
    # 1. KCF 추적기만 사용 (가장 빠르고 정확)
    if self.enable_kcf and self.kcf_tracker is not None:
        bbox = self._track_kcf(frame_u8)
        if bbox and self._validate_face_temperature(frame_thermal, bbox):
            return bbox
    
    # 2. 이전 bbox가 있으면 로컬 영역만 검색
    if self.last_bbox is not None and self.missed < self.lost_tolerance:
        bbox = self._search_local_area(frame_thermal, self.last_bbox)
        if bbox and self._validate_face_temperature(frame_thermal, bbox):
            return bbox
    
    # 3. 전체 프레임 검색 (최후의 수단, 느림)
    bbox = self._search_full_frame(frame_thermal)
    if bbox and self._validate_face_temperature(frame_thermal, bbox):
        return bbox
    
    return None
```

### 우선순위 2: ROI 추출 단순화
```python
def extract(self, frame, bbox, frame_u8=None):
    # 랜드마크는 주기적으로만 시도 (10프레임마다)
    if self._should_try_landmarks():
        landmarks = self.landmark_detector.detect(frame_u8, bbox)
        if landmarks:
            return self._extract_from_landmarks(landmarks, frame)
    
    # 실패 시 즉시 고정 비율 사용 (랜드마크 재시도 안 함)
    return self._extract_fixed_ratio(frame, bbox)
```

### 우선순위 3: 타원형 패턴 검증 캐싱
```python
def _validate_face_temperature(self, frame, bbox):
    # bbox가 변하지 않으면 캐시된 결과 사용
    cache_key = (bbox, id(frame))
    if cache_key in self._validation_cache:
        return self._validation_cache[cache_key]
    
    # 계산 후 캐싱
    result = self._do_validate(frame, bbox)
    self._validation_cache[cache_key] = result
    return result
```

### 우선순위 4: 전처리 결과 캐싱
```python
def _preprocess_frame(self, frame, face_bbox=None):
    # bbox가 변하지 않으면 캐시된 결과 사용
    cache_key = (id(frame), face_bbox)
    if cache_key in self._preprocess_cache:
        return self._preprocess_cache[cache_key]
    
    # 전처리 후 캐싱
    result = self._do_preprocess(frame, face_bbox)
    self._preprocess_cache[cache_key] = result
    return result
```

### 우선순위 5: 로깅 최소화
- 에러/경고만 로깅
- 디버그 로그는 환경 변수로 제어
- 주기적 로깅 제거 또는 간격 증가 (30초 → 60초)

## 예상 성능 향상

1. **얼굴 탐지**: 30-50% 속도 향상 (KCF 우선, 전체 프레임 검색 최소화)
2. **ROI 추출**: 20-30% 속도 향상 (랜드마크 주기적 시도, 실패 시 즉시 fallback)
3. **타원형 검증**: 10-15% 속도 향상 (캐싱)
4. **전처리**: 5-10% 속도 향상 (캐싱)
5. **로깅**: 2-5% 속도 향상 (오버헤드 감소)

**전체 예상**: 약 40-60% 성능 향상

## 구현 순서

1. 얼굴 탐지 단순화 (가장 큰 영향)
2. ROI 추출 단순화
3. 타원형 검증 캐싱
4. 전처리 캐싱
5. 로깅 최소화

