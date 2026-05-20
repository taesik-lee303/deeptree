# DeepTree

Raspberry Pi와 Raspberry Pi Pico WH 기반의 IoT 케어 시스템입니다. 센서 데이터 수집, Thermal rPPG 생체신호 측정, CareCall 음성 인터랙션, 감정 기반 Display/LED 피드백을 하나의 엣지 시스템으로 통합했습니다.

## Project Overview

- **목적**: 돌봄 환경에서 사용자 상태와 주변 환경을 수집하고, 음성 대화와 시각 피드백을 제공하는 엣지 케어 시스템 구현
- **핵심 기능**: 센서 데이터 수집, 비접촉 생체신호 측정, CareCall 음성 인터랙션, 감정/상태 기반 화면 및 LED 제어
- **주요 하드웨어**: Raspberry Pi 5, Raspberry Pi Pico WH, Thermal Camera, PIR Sensor, Air Sensor, Temperature/Humidity Sensor, Sound Sensor, Display, LED Module
- **주요 통신 방식**: MQTT, Kafka, UART

## Architecture

![DeepTree hardware architecture](docs/assets/hardware_architecture.png)

상세 하드웨어 구성과 데이터 흐름은 [Hardware Overview](docs/HARDWARE_OVERVIEW.md) 문서에서 확인할 수 있습니다.

## My Contribution

- Raspberry Pi 5와 Pico WH를 중심으로 한 하드웨어/소프트웨어 연동 구조 설계
- 센서 데이터가 UART, MQTT, Kafka를 통해 이동하는 데이터 흐름 정리
- Thermal rPPG, CareCall, Display, LED 모듈 간 연동 구조 구현 및 문서화
- 프로젝트 설명을 위한 시스템 아키텍처 및 데이터 플로우 다이어그램 작성

## Tech Stack

- **Language**: Python
- **Edge Device**: Raspberry Pi 5, Raspberry Pi Pico WH
- **Messaging**: MQTT, Kafka, UART
- **AI/Signal Processing**: STT/TTS, Thermal rPPG, emotion/state decision logic
- **Display/Feedback**: Sensor dashboard, emotion video display, LED module

## Repository Structure

```text
src/
  modules/
    carecall/   # CareCall voice interaction
    rppg/       # Thermal rPPG and color therapy integration
    display/    # Sensor and emotion display
  networks/     # Kafka, MQTT, UART communication
  test/         # Sensor, connector, and pipeline tests
docs/
  HARDWARE_OVERVIEW.md
  assets/
```

## Data Flow

![DeepTree hardware data flow](docs/assets/hardware_data_flow.png)

센서 데이터는 Pico WH에서 수집되어 UART 또는 MQTT를 통해 Raspberry Pi와 서버로 전달됩니다. Raspberry Pi 내부에서는 Kafka 기반 파이프라인을 통해 센서 이벤트, 생체신호 분석 결과, CareCall 상태, Display/LED 피드백이 연결됩니다.

## Notes

이 프로젝트는 단일 기능 구현보다 여러 하드웨어와 소프트웨어 모듈을 하나의 엣지 케어 시스템으로 통합하는 데 초점을 둔 프로젝트입니다.
