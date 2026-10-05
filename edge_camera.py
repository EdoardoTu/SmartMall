"""
Edge camera simulator (stands in for Raspberry Pi 5 + accelerator).
Runs YOLO11n on a video/webcam, counts people in LEFT / CENTER / RIGHT zones
and publishes only aggregated counts to MQTT (no raw video).

Usage:
  python edge_camera.py --video mall.mp4 --floor 1 --cam 1
  python edge_camera.py --video 0 --floor 2 --cam 2 --headless
"""
import argparse, json, time
import cv2
import paho.mqtt.client as mqtt
from ultralytics import YOLO

ZONES = ["left", "center", "right"]
COLORS = {"left": (255, 160, 0), "center": (0, 200, 0), "right": (0, 140, 255)}


def zone_of(cx, width):
    return ZONES[min(2, int(cx / width * 3))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default="0", help="video path or webcam index")
    ap.add_argument("--floor", type=int, default=1)
    ap.add_argument("--cam", type=int, default=1)
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--model", default="yolo11n.pt")
    ap.add_argument("--conf", type=float, default=0.4)
    ap.add_argument("--interval", type=float, default=1.0, help="publish period (s)")
    ap.add_argument("--headless", action="store_true", help="no preview window")
    a = ap.parse_args()

    cam_id = f"F{a.floor}C{a.cam}"
    topic = f"mall/floor{a.floor}/cam{a.cam}/zones"
    status_topic = f"mall/floor{a.floor}/cam{a.cam}/status"

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"edge-{cam_id}")
    client.will_set(status_topic, json.dumps({"camera_id": cam_id, "online": False}), qos=1, retain=True)
    client.on_connect = lambda c, u, f, rc, props=None: print(f"[MQTT] on_connect: {rc}")
    client.on_disconnect = lambda *args: print("[MQTT] disconnesso")
    print(f"[MQTT] connessione a {a.broker}:{a.port} ...")
    client.connect(a.broker, a.port)
    client.loop_start()
    client.publish(status_topic, json.dumps({"camera_id": cam_id, "online": True}), qos=1, retain=True)

    model = YOLO(a.model)
    src = int(a.video) if a.video.isdigit() else a.video
    cap = cv2.VideoCapture(src)
    last_pub = 0.0
    if not a.headless:
        cv2.namedWindow(cam_id, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(cam_id, 960, 540)

    try:
        while True:
            ok, frame = cap.read()
            if not ok:  # loop video files
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = cap.read()
                if not ok:
                    break
            h, w = frame.shape[:2]
            res = model(frame, classes=[0], conf=a.conf, verbose=False)[0]

            counts = {z: 0 for z in ZONES}
            for box in res.boxes.xyxy.cpu().numpy():
                x1, y1, x2, y2 = box
                z = zone_of((x1 + x2) / 2, w)
                counts[z] += 1
                if not a.headless:
                    cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), COLORS[z], 2)

            now = time.time()
            if now - last_pub >= a.interval:
                payload = {"camera_id": cam_id, "floor": a.floor, "ts": str(int(now * 1000)),
                           "zones": counts, "total": sum(counts.values()), "source": "yolo"}
                client.publish(topic, json.dumps(payload), qos=1, retain=True)
                last_pub = now
                print(f"[PUB] {topic} {json.dumps(payload)}")

            if not a.headless:
                # 1. Disegna una fascia scura in alto per contrastare il testo dei conteggi
                overlay = frame.copy()
                cv2.rectangle(overlay, (0, 0), (w, 45), (0, 0, 0), -1)
                cv2.addWeighted(overlay, 0.4, frame, 0.6, 0, frame)

                # 2. Linee divisorie ad alto contrasto (Bordo nero sotto, linea gialla brillante sopra)
                for i in (1, 2):
                    x_pos = w * i // 3
                    # Linea nera di sfondo più spessa (6px)
                    cv2.line(frame, (x_pos, 0), (x_pos, h), (0, 0, 0), 6)
                    # Linea gialla brillante centrale (2px)
                    cv2.line(frame, (x_pos, 0), (x_pos, h), (0, 255, 255), 2)

                # 3. Testi dei conteggi con contorno nero
                for i, z in enumerate(ZONES):
                    text = f"{z.upper()}: {counts[z]}"
                    pos = (w * i // 3 + 15, 30)
                    # Bordo nero del testo
                    cv2.putText(frame, text, pos, cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4)
                    # Testo colorato sopra
                    cv2.putText(frame, text, pos, cv2.FONT_HERSHEY_SIMPLEX, 0.8, COLORS[z], 2)

                cv2.imshow(cam_id, frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    finally:
        client.publish(status_topic, json.dumps({"camera_id": cam_id, "online": False}), qos=1, retain=True)
        client.loop_stop()
        client.disconnect()
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()