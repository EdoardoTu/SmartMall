import json
import time
import requests
import paho.mqtt.client as mqtt

MQTT_BROKER = "localhost"
MQTT_PORT = 1884   # <-- stesso del publisher
API_GATEWAY_URL = "https://8ua9q3h48a.execute-api.eu-north-1.amazonaws.com/prod"
API_KEY = "private-key"

buffer = []
BATCH_SIZE = 5
FLUSH_INTERVAL = 10
last_flush = time.time()


def send_to_aws(items):
    url = f"{API_GATEWAY_URL}/ingest"
    headers = {"Content-Type": "application/json", "x-api-key": API_KEY}
    try:
        r = requests.post(url, json={"items": items}, headers=headers, timeout=5)
        print(f"Stato HTTP: {r.status_code} — {r.text}")
    except Exception as e:
        print(f"[FORWARDER ERRORE] {e}")


def on_connect(client, userdata, flags, rc, properties=None):
    print(f"[MQTT] on_connect rc={rc}")
    if rc == 0:
        client.subscribe("mall/+/+/zones")
        client.subscribe("mall/+/+/shop/+/count")
        print("[MQTT] iscritto a mall/+/+/zones e shop/+/count")
    else:
        print(f"[MQTT] connessione fallita rc={rc}")


def on_disconnect(client, userdata, rc, properties=None):
    print(f"[MQTT] disconnesso rc={rc}")


def on_message(client, userdata, msg):
    global last_flush
    try:
        raw = json.loads(msg.payload.decode('utf-8'))

        if "zones" in raw and "camera_id" in raw:
            item = {
                "camera_id": raw["camera_id"],
                "ts": str(raw.get("ts", int(time.time() * 1000))),
                "floor": raw.get("floor", 0),
                "left": raw["zones"].get("left", 0),
                "center": raw["zones"].get("center", 0),
                "right": raw["zones"].get("right", 0),
                "total": raw.get("total", 0),
                "source": raw.get("source", "yolo"),
            }
            buffer.append(item)
            print(f"[BUFFER][ZONE] {raw['camera_id']} coda={len(buffer)}")

        elif "shop_id" in raw and "occupancy" in raw:
            item = {
                "shop_id": raw["shop_id"],
                "ts": str(raw.get("ts", int(time.time() * 1000))),
                "camera_id": raw.get("camera_id", ""),
                "floor": raw.get("floor", 0),
                "occupancy": raw.get("occupancy", 0),
                "entered": raw.get("entered", 0),
                "exited": raw.get("exited", 0),
                "source": raw.get("source", "sim"),
            }
            buffer.append(item)
            print(f"[BUFFER][SHOP] {raw['shop_id']} coda={len(buffer)}")
        else:
            return

        now = time.time()
        if len(buffer) >= BATCH_SIZE or (now - last_flush >= FLUSH_INTERVAL and len(buffer) > 0):
            send_to_aws(list(buffer))
            buffer.clear()
            last_flush = now

    except Exception as e:
        print(f"[FORWARDER ERRORE] Parsing: {e}")


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="aws-rest-forwarder")
client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_message = on_message

client.connect(MQTT_BROKER, MQTT_PORT)
client.loop_forever()