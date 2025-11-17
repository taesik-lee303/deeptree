# Thermal rPPG 시스템 전체 작동 플로우

## 개요
MLX9064X 열화상 카메라를 사용하여 얼굴을 탐지하고, 심박수(HR), 호흡수(RR), 온도 차이 등을 실시간으로 측정하는 시스템입니다.

## 전체 작동 플로우

### 1. 초기화 단계 (`__init__`)
```
1. 센서 초기화 (MLX9064XInterface)
   - I2C 통신 설정
   - 샘플링 레이트 설정 (기본 16Hz)

2. 얼굴 탐지기 초기화 (ThermalFaceDetector)
   - 전처리 파이프라인 설정 (CLAHE, Bilateral Filter)
   - 온도 임계값 설정
   - KCF 추적기 설정 (선택적)

3. 얼굴 랜드마크 검출기 초기화 (FaceLandmarkDetector)
   - MediaPipe Face Mesh 설정 (468 포인트)
   - ROI 위치 정확도 향상

4. ROI 관리자 초기화 (ROIManager)
   - ROI 세분화 설정 (얼굴이 클 때 자동 세분화)
   - 동적 위치 조정 설정

5. 신호 처리기 초기화
   - SignalProc (HR 계산용)
   - RespEstimator (RR 계산용)

6. AI 향상 기능 초기화 (선택적)
   - WaveletDenoiser (웨이블릿 노이즈 제거)
   - AdaptiveKalmanFilter (적응형 칼만 필터)
   - EnsembleROIOptimizer (앙상블 학습)
   - PersonalizedBiometricModel (개인화 모델)

7. MQTT 클라이언트 초기화 (선택적)
   - 실시간 데이터 전송
   - 세션 완료 시 데이터 전송
```

### 2. 메인 루프 (`run()`)

#### 2.1 프레임 읽기 및 전처리
```
1. 센서에서 프레임 읽기
   frame = sensor.read_frame()

2. 센서 회전 보정 (설정된 경우)
   - sensor_rotation_deg (기본 135°)
   - OpenCV 회전 변환 적용

3. Super-Resolution (선택적)
   - Multi-Frame Super-Resolution (MFSR)
   - 여러 프레임을 결합하여 해상도 향상
   - stride 설정으로 성능 최적화

4. 업스케일링
   - 기본 4배 업스케일 (up_scale=4)
   - 얼굴 탐지 정확도 향상
```

#### 2.2 얼굴 탐지 및 검증
```
1. 얼굴 탐지 (ThermalFaceDetector.detect)
   - 전처리: 온도 정규화, CLAHE, Bilateral Filter
   - 임계값 처리: ambient + delta 또는 percentile 기반
   - Morphology 연산: 노이즈 제거
   - Connected Components: 열원 영역 추출
   - 스코어링: 온도, 위치, 크기, 타원형 패턴 점수
   - 타원형 패턴 검증: 중심에서 둥글게 온도 분포 확인
   - 온도 검증: 얼굴 온도 범위, 핫 픽셀 비율, 분포 패턴

2. 얼굴 추적 (KCF 또는 템플릿 매칭)
   - 이전 프레임과의 연속성 확인
   - 위치 급변 감지 및 방지

3. bbox 안정성 검증
   - 크기 검증 (프레임의 1%~80%)
   - 연속성 검증 (이전 bbox와의 거리)
```

#### 2.3 Motion Compensation (선택적)
```
1. 얼굴 추적 안정성 확인
   - missed <= 2 (연속 실패가 적을 때만)
   - motion_level < 50.0 (과도한 움직임 없을 때만)

2. ECC (Enhanced Correlation Coefficient) 기반 변환
   - Affine 변환 행렬 계산
   - 움직임 보정 적용
```

#### 2.4 ROI 추출
```
1. 랜드마크 기반 ROI 추출 (우선)
   - MediaPipe Face Mesh로 정확한 위치 검출
   - 이마, 코, 왼쪽 볼, 오른쪽 볼 영역 추출

2. 얼굴 크기 기반 ROI 세분화 (얼굴이 클 때)
   - 얼굴이 프레임의 15% 이상일 때 활성화
   - 이마: 좌/중/우 3분할
   - 볼: 상/하 2분할
   - 코: 상/하 2분할
   - 추가: 눈썹, 턱 영역

3. 고정 비율 기반 ROI (랜드마크 실패 시)
   - 얼굴 bbox 비율 기반
   - 온도 분포 기반 동적 위치 조정

4. ROI 값 추출
   - 중심 패치 + 전체 영역 가중 평균
   - 중심 가중치: 90% (신호 강조)
```

#### 2.5 Presence Gate 검증
```
1. 기하/열 검증
   - bbox 존재 여부
   - 이마 온도 범위 (26~38°C)
   - ambient 대비 온도 차이

2. 스펙트럼 검증 (선택적)
   - ROI별 HR 계산
   - SNR, 하모닉 검증
   - 품질 기준 확인

3. 세션 관리
   - 얼굴 감지 시 세션 시작
   - 얼굴 미감지 시 타임아웃 체크 (기본 5초)
   - 세션 최소 시간: 45초
   - 세션 최대 시간: 75초
```

#### 2.6 신호 처리 및 건강 지표 계산

##### HR (심박수) 계산
```
1. 버퍼 확인
   - 최소 8초 데이터 필요 (기본)
   - ROI별 버퍼 확인

2. 전처리
   - Ambient 보정 (선택적)
   - 웨이블릿 노이즈 제거 (선택적)

3. FFT 분석
   - Bandpass 필터 (0.7~4.0 Hz)
   - FFT로 주파수 분석
   - 피크 검출 및 SNR 계산
   - 하모닉 검증 (2배/반배 교정)

4. ROI 가중치 계산
   - 앙상블 학습 기반 최적 가중치 (선택적)
   - 또는 동적 보정 (이마 우선, 발한/모션 페널티)

5. 최종 HR 계산
   - 가중 평균
   - 칼만 필터 적용 (선택적)
   - 개인화 보정 (선택적)
   - HR 점프 억제 (속도 제한 + EMA)
```

##### RR (호흡수) 계산
```
1. 코 ROI 버퍼 확인
   - 최소 12초 데이터 필요

2. FFT 분석
   - Bandpass 필터 (0.1~0.5 Hz)
   - FFT로 주파수 분석
   - 피크 검출

3. 최신 RR 값 유지
   - 계산 주기가 아니면 최신 값 사용
```

##### 온도 차이 계산
```
1. 이마, 코, 볼 온도 평균 (최근 5초)
2. ΔT_nose = 코 - 이마
3. ΔT_cheek = (왼쪽 볼 + 오른쪽 볼) / 2 - 이마
```

#### 2.7 세션 관리
```
1. 세션 시작
   - 얼굴 감지 시 자동 시작
   - session_start_ts 기록

2. 세션 업데이트
   - HR > 60 BPM이고 Q >= 기준일 때만 저장
   - 최고 품질 측정값 추적
   - 세션 통계 계산 (최대 HR, 최빈값 중앙값, 최고 Q)

3. 세션 완료 조건
   - 최소 시간(45초) 경과 + 품질 기준 만족 → 조기 완료
   - 최대 시간(75초) 경과 → 강제 완료

4. 세션 결과 전송
   - 세 가지 기준으로 각각 전송:
     * 최대 HR값
     * 최빈값 중앙값
     * 최고 Q값
   - MQTT로 전송 (total 토픽)
```

#### 2.8 실시간 MQTT 전송 (선택적)
```
1. 품질 체크
   - Q >= realtime_mqtt_quality_min

2. 주기 체크
   - realtime_mqtt_interval (기본 5초)

3. MQTT 전송
   - status 토픽으로 전송
   - HR, RR, Q, 온도 차이, 모션 레벨 등
```

#### 2.9 AI 모델 업데이트 (선택적)
```
1. 주기적 업데이트 (기본 300초)
   - 앙상블 학습 모델 재훈련
   - 개인화 모델 프로필 업데이트
```

#### 2.10 UI 업데이트 (디버그 모드)
```
1. 열화상 이미지 시각화
   - INFERNO 컬러맵 적용
   - bbox 및 ROI 박스 표시

2. 차트 표시
   - HR 히스토그램
   - 품질 히스토그램

3. 통계 표시
   - 샘플 수, FPS, 품질, RR, 온도 차이
   - 얼굴 인식 상태, 추적 상태
   - 아티팩트 정보 (발한, 모션)
   - 컬러 테라피 추천
```

## 주요 특징

### 1. 타원형 온도 분포 검증
- 얼굴은 중심(이마)에서 둥글게 온도가 분포됨
- 방사형 링 분석으로 타원형 패턴 확인
- 원형도 계산으로 얼굴 탐지 정확도 향상

### 2. ROI 세분화
- 얼굴이 가까이 갈 때 (프레임의 15% 이상)
- ROI를 더 세분화하여 측정점 증가
- 이마: 좌/중/우, 볼: 상/하, 코: 상/하

### 3. AI 향상 기능
- 웨이블릿 노이즈 제거
- 적응형 칼만 필터
- 앙상블 학습 기반 ROI 가중치 최적화
- 개인화된 생체신호 모델

### 4. 세션 관리
- 최소 45초, 최대 75초 측정
- 세 가지 기준으로 결과 전송
- 품질 기준 만족 시 조기 완료 가능

### 5. 실시간 모니터링
- 실시간 MQTT 전송 (status 토픽)
- 세션 완료 시 최종 결과 전송 (total 토픽)

## 성능 최적화

### 1. 라즈베리파이 최적화
- 메모리 제한 (512MB)
- CPU 스로틀링
- 정밀도 감소 (float32)

### 2. 계산 스로틀링
- HR 계산 주기: 0.75초
- RR 계산 주기: 2.0초
- Super-Resolution stride: 3
- Motion Compensation stride: 2

### 3. 버퍼 관리
- 얼굴 미감지 시 버퍼 감소
- 최대 버퍼 크기: 2048 샘플

## 설정 파라미터

### 주요 설정
- `sampling_rate`: 16.0 Hz
- `up_scale`: 4 (업스케일 배수)
- `sensor_rotation_deg`: 135.0° (센서 회전 보정)
- `ui_scale`: 2.5 (UI 확대 배수)
- `session_min_duration`: 45초
- `session_max_duration`: 75초

### AI 향상 기능
- `enable_wavelet_denoising`: True
- `enable_adaptive_filtering`: True
- `enable_ensemble_learning`: True
- `enable_personalized_model`: True

