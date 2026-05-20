# Sensor Pico Firmware

MicroPython firmware for the Raspberry Pi Pico W that collects environmental sensor data and sends it to the Raspberry Pi/server pipeline.

## Role

- Reads particulate/air sensor data.
- Reads DHT22 temperature and humidity data.
- Reads sound sensor data.
- Sends the combined JSON payload over UART.
- Publishes the same payload to MQTT.

## Data Output

The firmware builds one JSON object that can include `pm`, `dht22`, and `sound` fields, then sends it through UART and MQTT.

## Configuration

`config.py` contains public sample values only. For a real device, create `config_local.py` on the Pico and set private Wi-Fi and MQTT values there.
