# MQTT API 문서

이 문서는 DeepTree 프로젝트의 MQTT 메시지 구조와 필드 설명을 제공합니다.

## 빠른 시작

### 연결 정보

- **브로커 주소**: `203.250.148.52`
- **포트**: `20516`
- **토픽**:
  - 실시간: `taesik/therapy/status`
  - 세션 종료: `taesik/therapy/total`
  - Pico: `pico/color`

### 빠른 구독 예제

```bash
# mosquitto_sub 사용
mosquitto_sub -h 203.250.148.52 -p 20516 -t "taesik/therapy/status" -t "taesik/therapy/total"
```

## 개요

DeepTree는 두 가지 MQTT 토픽을 통해 색상 치료 추천 데이터를 전송합니다:

- **`taesik/therapy/status`**: 실시간 측정 데이터 (주기적 전송)
- **`taesik/therapy/total`**: 세션 종료 시 최종 측정 데이터 (세 가지 기준으로 각각 전송)
- **`pico/color`**: Pico 호환 간소화 데이터 (선택적)

## 토픽별 상세 설명

### 1. `taesik/therapy/status` (실시간 토픽)

**전송 주기**: 약 5초마다 (설정 가능)  
**전송 조건**: 
- 얼굴이 감지되고 HR 값이 있을 때
- 신호 품질(Q) ≥ 0.3
- 세션이 활성화되어 있을 때

**메시지 구조**:

```json
{
  "rgb": [100, 149, 237],
  "intensity": 0.75,
  "mode": "relax",
  "duration": 30,
  "confidence": 0.85,
  "metrics": {
    "hr": 72.5,
    "rr": 16.2,
    "q": 0.65,
    "dT_nose": -0.15,
    "dT_cheek": 0.05,
    "forehead": 36.2,
    "motion_px": 120,
    "artifacts": null,
    "measurement_type": "realtime",
    "session_active": true,
    "session_elapsed": 25.3
  },
  "ts": 1704067200
}
```

### 2. `taesik/therapy/total` (세션 종료 토픽)

**전송 시점**: 
- 세션이 75초에 종료될 때
- 또는 조기 완료 조건을 만족할 때 (45초 이상 + Q ≥ 0.55)

**특징**: 세 가지 기준으로 각각 전송됩니다 (총 3개의 메시지):
- `max_hr`: 최대 HR 값을 가진 측정값의 **모든 정보**
- `mode_median`: 최빈값 중앙값에 가장 가까운 측정값의 **모든 정보**
- `best_q`: 최고 품질(Q) 값을 가진 측정값의 **모든 정보**

**중요**: 각 메시지는 해당 기준에 맞는 측정값의 **전체 정보**(hr, rr, q, dT_nose, dT_cheek, forehead, motion_px, artifacts 등)를 포함합니다.

**메시지 구조 예시**:

#### 1. 최대 HR값 기준 (`measurement_type: "max_hr"`)

```json
{
  "rgb": [100, 149, 237],
  "intensity": 0.75,
  "mode": "relax",
  "duration": 30,
  "confidence": 0.85,
  "metrics": {
    "hr": 78.5,
    "rr": 18.2,
    "q": 0.72,
    "dT_nose": -0.18,
    "dT_cheek": 0.03,
    "forehead": 36.3,
    "motion_px": 95,
    "artifacts": null,
    "measurement_type": "max_hr",
    "session_stats": {
      "hr_max": 78.5,
      "hr_mode_median": 72.3,
      "q_max": 0.82,
      "total_measurements": 45
    }
  },
  "ts": 1704067200
}
```

#### 2. 최빈값 중앙값 기준 (`measurement_type: "mode_median"`)

```json
{
  "rgb": [100, 149, 237],
  "intensity": 0.75,
  "mode": "relax",
  "duration": 30,
  "confidence": 0.85,
  "metrics": {
    "hr": 72.3,
    "rr": 16.5,
    "q": 0.68,
    "dT_nose": -0.12,
    "dT_cheek": 0.05,
    "forehead": 36.2,
    "motion_px": 110,
    "artifacts": null,
    "measurement_type": "mode_median",
    "session_stats": {
      "hr_max": 78.5,
      "hr_mode_median": 72.3,
      "q_max": 0.82,
      "total_measurements": 45
    }
  },
  "ts": 1704067200
}
```

#### 3. 최고 Q값 기준 (`measurement_type: "best_q"`)

```json
{
  "rgb": [100, 149, 237],
  "intensity": 0.80,
  "mode": "relax",
  "duration": 30,
  "confidence": 0.92,
  "metrics": {
    "hr": 74.1,
    "rr": 17.0,
    "q": 0.82,
    "dT_nose": -0.10,
    "dT_cheek": 0.04,
    "forehead": 36.2,
    "motion_px": 85,
    "artifacts": null,
    "measurement_type": "best_q",
    "session_stats": {
      "hr_max": 78.5,
      "hr_mode_median": 72.3,
      "q_max": 0.82,
      "total_measurements": 45
    }
  },
  "ts": 1704067200
}
```

### 3. `pico/color` (Pico 호환 토픽)

**전송 조건**: `also_pico=True`일 때 함께 전송  
**용도**: 간단한 RGB 제어가 필요한 디바이스용

**메시지 구조**:

```json
{
  "r": 100,
  "g": 149,
  "b": 237,
  "intensity": 0.75
}
```

## 필드 상세 설명

### 공통 필드 (최상위 레벨)

| 필드명 | 타입 | 설명 | 예시 |
|--------|------|------|------|
| `rgb` | `[int, int, int]` | 추천 색상의 RGB 값 (0-255) | `[100, 149, 237]` |
| `intensity` | `float` | 색상 강도 (0.0 ~ 1.0) | `0.75` |
| `mode` | `string` | 색상 치료 모드 | `"relax"`, `"energize"`, `"balance"` 등 |
| `duration` | `int` | 추천 지속 시간 (초) | `30` |
| `confidence` | `float` | 추천 신뢰도 (0.0 ~ 1.0) | `0.85` |
| `metrics` | `object` | 생리 지표 데이터 (아래 참조) | - |
| `ts` | `int` | 타임스탬프 (Unix epoch 초) | `1704067200` |

### `metrics` 객체 필드

#### 생리 지표 필드

| 필드명 | 타입 | 설명 | 단위 | 범위/예시 |
|--------|------|------|------|-----------|
| `hr` | `float` | 심박수 (Heart Rate) | BPM (beats per minute) | `60.0 ~ 200.0` |
| `rr` | `float \| null` | 호흡수 (Respiration Rate) | brpm (breaths per minute) | `12.0 ~ 24.0`, `null` 가능 |
| `q` | `float` | 신호 품질 (Quality) | 0.0 ~ 1.0 | `0.0` (나쁨) ~ `1.0` (좋음) |
| `dT_nose` | `float \| null` | 코 온도 차이 (코 - 이마) | °C | `-0.5 ~ 0.5`, 음수면 냉각 |
| `dT_cheek` | `float \| null` | 볼 온도 차이 (볼 평균 - 이마) | °C | `-0.5 ~ 0.5` |
| `forehead` | `float \| null` | 이마 온도 | °C | `35.0 ~ 38.0` |
| `motion_px` | `int` | 움직임 픽셀 수 | 픽셀 | `0` 이상, 낮을수록 안정적 |
| `artifacts` | `string \| null` | 측정 방해 요인 | 문자열 | `"sweat"`, `"motion"`, `null` |

#### 세션 관련 필드 (실시간 토픽)

| 필드명 | 타입 | 설명 | 예시 |
|--------|------|------|------|
| `measurement_type` | `string` | 측정 유형 | `"realtime"` |
| `session_active` | `boolean` | 세션 활성화 여부 | `true` |
| `session_elapsed` | `float` | 세션 경과 시간 | `25.3` (초) |

#### 세션 관련 필드 (세션 종료 토픽)

| 필드명 | 타입 | 설명 | 예시 |
|--------|------|------|------|
| `measurement_type` | `string` | 측정 기준 | `"max_hr"`, `"mode_median"`, `"best_q"` |
| `session_stats` | `object` | 세션 통계 데이터 (아래 참조) | - |

### `session_stats` 객체 필드 (세션 종료 토픽만)

| 필드명 | 타입 | 설명 | 예시 |
|--------|------|------|------|
| `hr_max` | `float \| null` | 세션 중 최대 HR 값 | `78.5` |
| `hr_mode_median` | `float \| null` | 세션 중 최빈값 중앙값 HR | `72.3` |
| `q_max` | `float \| null` | 세션 중 최고 품질(Q) 값 | `0.82` |
| `total_measurements` | `int` | 세션 중 유효 측정값 개수 | `45` |

## 색상 치료 모드 (`mode`)

| 모드 | 설명 | 일반적인 RGB 범위 |
|------|------|-------------------|
| `relax` | 진정/이완 | 파란색 계열 (100-150, 100-200, 200-255) |
| `energize` | 활성화/각성 | 주황/빨강 계열 (200-255, 100-200, 0-100) |
| `balance` | 균형 | 녹색/청록 계열 (0-150, 150-255, 100-200) |
| `cooling` | 냉각 | 청록/파랑 계열 (0-100, 150-255, 200-255) |
| `warming` | 온난화 | 주황/노랑 계열 (200-255, 150-255, 0-150) |
| `focus` | 집중 | 보라/청록 계열 (100-200, 0-150, 150-255) |
| `deep_relax` | 깊은 이완 | 어두운 파랑/보라 계열 (50-100, 0-100, 100-200) |

## 데이터 해석 가이드

### 신호 품질 (`q`) 해석

- **0.8 이상**: 매우 좋음, 신뢰 가능
- **0.5 ~ 0.8**: 양호, 일반적으로 신뢰 가능
- **0.3 ~ 0.5**: 보통, 주의 깊게 해석 필요
- **0.3 미만**: 낮음, 신뢰도 낮음 (실시간 전송에서는 제외됨)

### 온도 차이 (`dT_nose`, `dT_cheek`) 해석

- **음수 값**: 해당 부위가 이마보다 차갑다 (교감신경 활성화 가능)
- **0 근처**: 온도 차이 없음 (안정 상태)
- **양수 값**: 해당 부위가 이마보다 따뜻하다

### 움직임 (`motion_px`) 해석

- **0 ~ 50**: 매우 안정적
- **50 ~ 150**: 보통
- **150 이상**: 움직임이 많음, 측정 정확도 저하 가능

### Artifacts 해석

- **`null`**: 방해 요인 없음
- **`"sweat"`**: 땀으로 인한 측정 방해
- **`"motion"`**: 움직임으로 인한 측정 방해
- **`"sweat,motion"`**: 여러 방해 요인 (쉼표로 구분)

## 예제 코드

### Python (paho-mqtt)

```python
import paho.mqtt.client as mqtt
import json

def on_message(client, userdata, msg):
    data = json.loads(msg.payload.decode())
    
    # 색상 정보
    rgb = data['rgb']
    intensity = data['intensity']
    mode = data['mode']
    
    # 생리 지표
    metrics = data['metrics']
    hr = metrics.get('hr')
    rr = metrics.get('rr')
    q = metrics.get('q')
    
    print(f"HR: {hr} BPM, RR: {rr} brpm, Quality: {q}")
    print(f"Color: RGB{rgb}, Mode: {mode}, Intensity: {intensity}")

client = mqtt.Client()
client.on_message = on_message
client.connect("203.250.148.52", 20516)
client.subscribe("taesik/therapy/status")
client.subscribe("taesik/therapy/total")
client.loop_forever()
```

### Node.js (mqtt)

```javascript
const mqtt = require('mqtt');

const client = mqtt.connect('mqtt://203.250.148.52:20516');

client.on('connect', () => {
  client.subscribe('taesik/therapy/status');
  client.subscribe('taesik/therapy/total');
});

client.on('message', (topic, message) => {
  const data = JSON.parse(message.toString());
  
  // 색상 정보
  const { rgb, intensity, mode } = data;
  
  // 생리 지표
  const { hr, rr, q } = data.metrics;
  
  console.log(`HR: ${hr} BPM, RR: ${rr} brpm, Quality: ${q}`);
  console.log(`Color: RGB[${rgb.join(',')}], Mode: ${mode}, Intensity: ${intensity}`);
});
```

## 주의사항

1. **null 값 처리**: `rr`, `dT_nose`, `dT_cheek`, `forehead`는 측정 실패 시 `null`일 수 있습니다.
2. **타임스탬프**: `ts`는 Unix epoch 초 단위입니다. 밀리초가 필요하면 `ts * 1000`을 사용하세요.
3. **세션 종료 메시지**: 세션 종료 시 **세 가지 메시지가 각각 전송**됩니다:
   - `measurement_type: "max_hr"` - 최대 HR값 측정값의 모든 정보
   - `measurement_type: "mode_median"` - 최빈값 중앙값 측정값의 모든 정보
   - `measurement_type: "best_q"` - 최고 Q값 측정값의 모든 정보
4. **실시간 전송 제한**: 실시간 전송은 신호 품질이 낮거나 얼굴이 감지되지 않으면 전송되지 않습니다.
5. **세션 통계**: `session_stats`는 세 가지 메시지 모두에 동일하게 포함되며, 세션 전체의 통계 정보를 제공합니다.

## 트러블슈팅

### 메시지를 받지 못하는 경우

1. **연결 확인**
   ```bash
   # MQTT 브로커 연결 테스트
   mosquitto_pub -h 203.250.148.52 -p 20516 -t "test" -m "test"
   ```

2. **토픽 구독 확인**
   - `taesik/therapy/status`: 실시간 데이터 (5초마다)
   - `taesik/therapy/total`: 세션 종료 시만 (75초마다)

3. **전송 조건 확인**
   - 실시간: 얼굴 감지 + HR 값 존재 + Q ≥ 0.3
   - 세션 종료: 세션 75초 경과 또는 조기 완료 조건 만족

### 데이터가 null인 경우

- `rr`, `dT_nose`, `dT_cheek`, `forehead`는 측정 실패 시 `null`일 수 있습니다.
- 최소 12초의 데이터가 필요하므로 세션 초기에는 `rr`이 `null`일 수 있습니다.

### 세션 종료 메시지가 3개가 아닌 경우

- 세션 통계가 없으면 (HR 60 초과 측정값이 없으면) `best` 값을 세 가지 모두로 사용합니다.
- 정상적으로는 항상 3개의 메시지가 전송됩니다.

## FAQ

**Q: 세션 종료 시 왜 3개의 메시지를 보내나요?**  
A: 세 가지 다른 기준(max_hr, mode_median, best_q)으로 최적의 측정값을 각각 선택하여 전송합니다. 수신 측에서 용도에 맞게 선택하여 사용할 수 있습니다.

**Q: 실시간 메시지가 오지 않아요.**  
A: 얼굴이 감지되고, HR 값이 있으며, 신호 품질(Q)이 0.3 이상이어야 전송됩니다. 세션이 활성화되어 있는지 확인하세요.

**Q: `session_stats`는 모든 메시지에 동일한가요?**  
A: 네, 세 가지 메시지 모두에 동일한 `session_stats`가 포함됩니다. 이는 세션 전체의 통계 정보입니다.

**Q: `measurement_type`으로 메시지를 구분할 수 있나요?**  
A: 네, `metrics.measurement_type` 필드로 구분할 수 있습니다:
- `"realtime"`: 실시간 메시지
- `"max_hr"`, `"mode_median"`, `"best_q"`: 세션 종료 메시지

## 설정

MQTT 연결 설정은 환경 변수로 변경 가능합니다:

- `MQTT_HOST`: MQTT 브로커 주소 (기본: `203.250.148.52`)
- `MQTT_PORT`: MQTT 브로커 포트 (기본: `20516`)
- `MQTT_TOPIC_BASE`: 토픽 베이스 (기본: `taesik/therapy`)
- `MQTT_PICO_TOPIC`: Pico 토픽 (기본: `pico/color`)
- `MQTT_USERNAME`: 인증 사용자명 (선택)
- `MQTT_PASSWORD`: 인증 비밀번호 (선택)
- `MQTT_TLS`: TLS 사용 여부 (기본: `false`)

## 관련 문서

- 프로젝트 저장소: [GitHub 링크]
- 설정 파일: `src/networks/mqtt/mqtt_config.py`
- 발행 코드: `src/networks/mqtt/mqtt_publisher.py`

## 버전 정보

- 문서 버전: 1.0
- API 버전: 1.0
- 최종 업데이트: 2025-01

## 변경 이력

- **v1.0 (2025-01)**: 초기 문서 작성
  - 실시간/세션 종료 토픽 분리
  - 세 가지 기준별 메시지 전송 명시

