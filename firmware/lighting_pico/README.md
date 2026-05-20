# Lighting Pico Firmware

MicroPython firmware for the Raspberry Pi Pico W that controls a NeoPixel LED module through MQTT.

## Role

- Connects to Wi-Fi.
- Subscribes to the `pico/color` MQTT topic.
- Receives JSON payloads with `r`, `g`, `b`, and `intensity`.
- Applies the received color to the NeoPixel LED module.

## Example Payload

```json
{
  "r": 255,
  "g": 120,
  "b": 40,
  "intensity": 0.8
}
```

## Configuration

`config.py` contains public sample values only. For a real device, create `config_local.py` on the Pico and set private Wi-Fi and MQTT values there.
