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


def publish_to_mqtt(payload):
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"render_bridge_{uuid.uuid4()}"
    )

    client.username_pw_set(
        HIVEMQ_USERNAME,
        HIVEMQ_PASSWORD
    )

    client.tls_set(
        cert_reqs=ssl.CERT_REQUIRED
    )

    client.connect(
        HIVEMQ_HOST,
        HIVEMQ_PORT,
        keepalive=60
    )

    client.loop_start()

    result = client.publish(
        HIVEMQ_TOPIC,
        json.dumps(payload, ensure_ascii=False),
        qos=1
    )

    result.wait_for_publish()

    client.loop_stop()
    client.disconnect()


def validate_payload(payload):
    required = [
        "title",
        "date",
    ]

    missing = [
        field for field in required
        if not payload.get(field)
    ]

    if missing:
        return False, "Fehlende Felder: " + ", ".join(missing)

    return True, None


@app.route("/")
def health():
    return jsonify({
        "success": True,
        "service": "calendar-render-bridge"
    })


@app.route("/incoming-appointment", methods=["POST"])
def incoming_appointment():

    token = request.headers.get("X-Webhook-Token")

    if not WEBHOOK_TOKEN or token != WEBHOOK_TOKEN:
        return jsonify({
            "success": False,
            "message": "Unauthorized"
        }), 401

    payload = request.get_json() or {}

    is_valid, error = validate_payload(payload)

    if not is_valid:
        return jsonify({
            "success": False,
            "message": error
        }), 400

    payload.setdefault("external_id", str(uuid.uuid4()))
    payload.setdefault("source", "ios_shortcut")
    payload.setdefault(
        "received_at",
        datetime.utcnow().isoformat()
    )

    publish_to_mqtt(payload)

    return jsonify({
        "success": True,
        "external_id": payload["external_id"]
    })
