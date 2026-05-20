# ===== mqtt_module.py (MicroPython용) =====
import time
import os

# MicroPython 환경
import network
try:
    from umqtt.robust import MQTTClient
except:
    from umqtt.simple import MQTTClient  # robust 없으면 simple 사용

try:
    import config_local as config
except ImportError:
    import config

# ---- 사용자 설정 ----
WIFI_SSID     = config.WIFI_SSID
WIFI_PASSWORD = config.WIFI_PASSWORD

MQTT_HOST     = config.MQTT_HOST
MQTT_PORT     = config.MQTT_PORT
MQTT_USER     = config.MQTT_USER
MQTT_PASSWORD = config.MQTT_PASSWORD
MQTT_TOPIC    = config.MQTT_TOPIC

_client = None
_connected = False

def _wifi_connect(timeout_ms=15000):
    wlan = network.WLAN(network.STA_IF)
    if not wlan.active():
        wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        t0 = time.ticks_ms()
        while not wlan.isconnected():
            time.sleep_ms(100)
            if time.ticks_diff(time.ticks_ms(), t0) > timeout_ms:
                raise RuntimeError("WiFi connect timeout")
    return True

def _make_client():
    # client_id는 고유하게
    try:
        import ubinascii, machine
        cid = b"pico-" + ubinascii.hexlify(machine.unique_id())
    except:
        cid = b"pico-client"
    cli = MQTTClient(client_id=cid,
                     server=MQTT_HOST,
                     port=MQTT_PORT,
                     user=(MQTT_USER or None),
                     password=(MQTT_PASSWORD or None),
                     keepalive=30)
    return cli

def init_mqtt():
    global _client, _connected
    try:
        _wifi_connect()
        _client = _make_client()
        _client.connect(False)
        _connected = True
        print("[MQTT] connected to {}:{}".format(MQTT_HOST, MQTT_PORT))
        return True
    except Exception as e:
        print("[MQTT] init failed:", e)
        _client = None
        _connected = False
        return False

def publish(data_str):
    """
    data_str: JSON 문자열 그대로 전달 (가공/평균 없음)
    반환: True/False
    """
    global _client, _connected
    if not _connected or _client is None:
        return False
    try:
        # 문자열을 그대로 전송
        if isinstance(data_str, str):
            payload = data_str.encode('utf-8')
        else:
            payload = data_str  # 이미 bytes면 그대로
        _client.publish(MQTT_TOPIC, payload, retain=False, qos=0)
        return True
    except Exception as e:
        print("[MQTT] publish error:", e)
        try:
            _client.disconnect()
        except:
            pass
        _client = None
        _connected = False
        return False
