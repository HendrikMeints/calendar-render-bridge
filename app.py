import json
import os
import ssl
import uuid
from datetime import datetime

from flask import Flask, request, jsonify
import paho.mqtt.client as mqtt


app = Flask(__name__)


WEBHOOK_TOKEN = os.environ.get("WEBHOOK_TOKEN")

HIVEMQ_HOST = os.environ.get("HIVEMQ_HOST")
HIVEMQ_PORT = int(os.environ.get("HIVEMQ_PORT", "8883"))
HIVEMQ_USERNAME = os.environ.get("HIVEMQ_USERNAME")
HIVEMQ_PASSWORD = os.environ.get("HIVEMQ_PASSWORD")

HIVEMQ_TOPIC = os.environ.get(
    "HIVEMQ_TOPIC",
    "calendar_app/incoming_appointments"
)

HIVEMQ_HEALTH_TOPIC = os.environ.get(
    "HIVEMQ_HEALTH_TOPIC",
    "calendar_app/health/incoming"
)


def unwrap_shortcut_payload(payload):
    if not isinstance(payload, dict):
        return {}

    if "Wörterbuch" in payload and isinstance(payload["Wörterbuch"], dict):
        return payload["Wörterbuch"]

    if "Dictionary" in payload and isinstance(payload["Dictionary"], dict):
        return payload["Dictionary"]

    if "" in payload and isinstance(payload[""], dict):
        return payload[""]

    return payload


def publish_to_mqtt(payload, topic):
    import time

    state = {
        "connected": False,
        "published": False,
    }

    def on_connect(client, userdata, flags, reason_code, properties=None):
        print(f"MQTT connected: {reason_code}")
        state["connected"] = True

    def on_publish(client, userdata, mid, reason_code=None, properties=None):
        print(f"MQTT publish confirmed. MID={mid}, reason={reason_code}")
        state["published"] = True

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"render_bridge_{uuid.uuid4()}"
    )

    client.username_pw_set(HIVEMQ_USERNAME, HIVEMQ_PASSWORD)
    client.tls_set(cert_reqs=ssl.CERT_REQUIRED)

    client.on_connect = on_connect
    client.on_publish = on_publish

    print("MQTT HOST:", HIVEMQ_HOST)
    print("MQTT PORT:", HIVEMQ_PORT)
    print("MQTT TOPIC:", topic)

    client.connect(HIVEMQ_HOST, HIVEMQ_PORT, keepalive=60)
    client.loop_start()

    for _ in range(50):
        if state["connected"]:
            break
        time.sleep(0.1)

    if not state["connected"]:
        client.loop_stop()
        client.disconnect()
        raise RuntimeError("MQTT Verbindung wurde nicht bestätigt.")

    result = client.publish(
        topic,
        json.dumps(payload, ensure_ascii=False),
        qos=1
    )

    result.wait_for_publish(timeout=10)

    client.loop_stop()
    client.disconnect()

    if not state["published"]:
        raise RuntimeError("MQTT Publish wurde nicht bestätigt.")


def validate_appointment_payload(payload):
    required = ["title", "date"]

    missing = [
        field for field in required
        if not payload.get(field)
    ]

    if missing:
        return False, "Fehlende Felder: " + ", ".join(missing)

    return True, None


def validate_health_payload(payload):
    payload_type = payload.get("type")

    if payload_type == "health_weight":
        if payload.get("weight_kg") is None:
            return False, "Fehlendes Feld: weight_kg"
        return True, None

    if payload_type == "health_blood_pressure":
        missing = []
        if payload.get("systolic") is None:
            missing.append("systolic")
        if payload.get("diastolic") is None:
            missing.append("diastolic")

        if missing:
            return False, "Fehlende Felder: " + ", ".join(missing)

        return True, None

    return False, "Unbekannter Health-Typ. Erlaubt: health_weight, health_blood_pressure"


def check_token():
    token = request.headers.get("X-Webhook-Token")
    return bool(WEBHOOK_TOKEN and token == WEBHOOK_TOKEN)


@app.route("/")
def index():
    return jsonify({
        "success": True,
        "service": "calendar-render-bridge"
    })


@app.route("/debug-token")
def debug_token():
    token = os.environ.get("WEBHOOK_TOKEN")

    return jsonify({
        "has_token": bool(token),
        "token_length": len(token) if token else 0,
        "token_preview": token[:3] + "..." + token[-3:] if token and len(token) >= 6 else None
    })


@app.route("/debug-env")
def debug_env():
    return jsonify({
        "has_webhook_token": bool(os.environ.get("WEBHOOK_TOKEN")),
        "has_hivemq_host": bool(os.environ.get("HIVEMQ_HOST")),
        "has_hivemq_username": bool(os.environ.get("HIVEMQ_USERNAME")),
        "has_hivemq_password": bool(os.environ.get("HIVEMQ_PASSWORD")),
        "hivemq_port": os.environ.get("HIVEMQ_PORT"),
        "hivemq_topic": os.environ.get("HIVEMQ_TOPIC"),
        "hivemq_health_topic": os.environ.get("HIVEMQ_HEALTH_TOPIC"),
    })


@app.route("/incoming-appointment", methods=["POST"])
def incoming_appointment():
    if not check_token():
        return jsonify({
            "success": False,
            "message": "Unauthorized"
        }), 401

    payload = request.get_json() or {}
    print("RAW APPOINTMENT PAYLOAD:", payload)

    payload = unwrap_shortcut_payload(payload)

    is_valid, error = validate_appointment_payload(payload)
    if not is_valid:
        return jsonify({
            "success": False,
            "message": error
        }), 400

    payload.setdefault("external_id", str(uuid.uuid4()))
    payload.setdefault("source", "ios_shortcut")
    payload.setdefault("received_at", datetime.utcnow().isoformat())

    publish_to_mqtt(payload, HIVEMQ_TOPIC)

    return jsonify({
        "success": True,
        "external_id": payload["external_id"],
        "topic": HIVEMQ_TOPIC
    })


@app.route("/incoming-health", methods=["POST"])
def incoming_health():
    if not check_token():
        return jsonify({
            "success": False,
            "message": "Unauthorized"
        }), 401

    payload = request.get_json() or {}
    print("RAW HEALTH PAYLOAD:", payload)

    payload = unwrap_shortcut_payload(payload)

    is_valid, error = validate_health_payload(payload)
    if not is_valid:
        return jsonify({
            "success": False,
            "message": error
        }), 400

    payload.setdefault("external_id", str(uuid.uuid4()))
    payload.setdefault("source", "ios_shortcut")
    payload.setdefault("received_at", datetime.utcnow().isoformat())

    publish_to_mqtt(payload, HIVEMQ_HEALTH_TOPIC)

    return jsonify({
        "success": True,
        "external_id": payload["external_id"],
        "topic": HIVEMQ_HEALTH_TOPIC
    })
