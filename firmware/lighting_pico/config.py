# Public sample configuration for the lighting Pico firmware.
# For real devices, copy this file to config_local.py and set private values there.

WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASS = "YOUR_WIFI_PASSWORD"

MQTT_HOST = "YOUR_MQTT_HOST"
MQTT_PORT = 1883
MQTT_TOPIC = "pico/color"

NEO_PIN = 1
NEO_COUNT = 32
DEBUG = True
