# deepcare-edge (Monorepo 계층 분리)

입력 **Connectors**(UART/MQTT/HTTP)와 **Kafka 파이프라인**을 분리한 구조입니다.

```
deepcare-edge/
├── connectors/
│   └── uart/
│       └── uart_io.py
├── common/
│   ├── kafka/kafka_utils.py
│   ├── normalize/normalize_utils.py
│   └── schema/schema_utils.py
├── pipelines/
│   └── kafka/
│       ├── producers/
│       │   ├── uart_to_kafka.py
│       │   ├── mqtt_to_kafka.py
│       │   └── http_to_kafka.py
│       ├── config/
│       │   ├── topics.yaml
│       │   └── schemas/sensor-events.v1.json
│       └── scripts/
│           ├── create_topics.py
│           └── healthcheck.py
├── systemd/
│   ├── uart-to-kafka.service
│   ├── mqtt-to-kafka.service
│   └── http-to-kafka.service
├── .env
└── requirements.txt
```

## 설치
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=$(pwd)   # 또는 bashrc에 추가
python pipelines/kafka/scripts/create_topics.py
python pipelines/kafka/scripts/healthcheck.py
```

## 실행
### UART → Kafka
```bash
python pipelines/kafka/producers/uart_to_kafka.py
```

### MQTT → Kafka
```bash
python pipelines/kafka/producers/mqtt_to_kafka.py
```

### HTTP → Kafka
```bash
python pipelines/kafka/producers/http_to_kafka.py
```

## 정규화 규칙(공통)
- noise: `noise|noise_db|sound|sound_db` → `noise`
- pir: `pir|motion|motion_detected|ir` → `pir` (0/1)
- temp: `temp|temperature|t` → `temp`
- humid: `humid|humidity|h` → `humid`
- PM: `pm2_5|pm2.5`→`pm25`, `pm1_0`→`pm1`, `pm10_0`→`pm10`
- 기타 키는 `sensors.extra`로 보존

## systemd 배포(선택)
```bash
sudo cp -r deepcare-edge /opt/
cd /opt/deepcare-edge
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

sudo cp systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now uart-to-kafka.service
# 또는 mqtt-to-kafka.service / http-to-kafka.service
```
