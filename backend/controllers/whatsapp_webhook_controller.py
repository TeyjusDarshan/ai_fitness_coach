"""Webhook for the WhatsApp Business (Cloud API) account the coach shares
with clients (see COACH_WHATSAPP_NUMBER in frontend/src/constants.ts).

Meta forwards every inbound message on that number here as a POST. The
"Share Session with Coach" button (frontend/src/utils.ts:buildCoachShareMessage)
embeds "Session ID: <id>" / "Day: <n>" lines in the shared text, so a message
that parses those out is treated as a workout-complete trigger: we ack it
immediately, then publish a workout-complete event so
workout_analysis_consumer can generate the analysis/voice note and push it
back to the sender once it's ready.
"""
import logging
import os
import re

from flask import Blueprint, jsonify, request

from backend.kafka_producer import KafkaProducerClient
from whatsapp_client import WhatsAppClient

logger = logging.getLogger(__name__)

whatsapp_webhook_bp = Blueprint("whatsapp_webhook", __name__)

whatsapp_client = WhatsAppClient()
kafka_producer = KafkaProducerClient()

# Matches the "Session ID: <id>" / "Day: <n>" lines added in
# frontend/src/utils.ts:buildCoachShareMessage.
_SESSION_ID_RE = re.compile(r"Session ID:\s*(\d+)")
_DAY_RE = re.compile(r"Day:\s*(\d+)")

WORKOUT_RECEIVED_MESSAGE = "Amazing session! Looking into your workout"


@whatsapp_webhook_bp.get("/webhooks/whatsapp")
def verify_webhook():
    """Meta's one-time handshake for registering the webhook URL."""
    if (
        request.args.get("hub.mode") == "subscribe"
        and request.args.get("hub.verify_token") == os.environ["WHATSAPP_VERIFY_TOKEN"]
    ):
        return request.args.get("hub.challenge", ""), 200
    return jsonify({"error": "Verification failed."}), 403


@whatsapp_webhook_bp.post("/webhooks/whatsapp")
def receive_message():
    body = request.get_json(silent=True) or {}
    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            for message in change.get("value", {}).get("messages", []):
                _handle_message(message)

    # Always ack with 200 once entries are looked at — Meta retries (and can
    # eventually disable the webhook) on a non-2xx response, and any failure
    # handling an individual message is already logged in _handle_message.
    return jsonify({"status": "received"}), 200


def _handle_message(message: dict) -> None:
    sender = message.get("from")
    text = (message.get("text") or {}).get("body", "")
    if not sender or not text:
        return

    session_id, day_number = _extract_session_and_day(text)
    if session_id is None or day_number is None:
        logger.info("No session_id/day_number found in WhatsApp message from %s", sender)
        return

    try:
        whatsapp_client.send_text(sender, WORKOUT_RECEIVED_MESSAGE)
    except Exception:
        logger.exception("Failed to send WhatsApp ack to %s", sender)

    try:
        kafka_producer.send_workout_complete_event(session_id, day_number, sender)
    except Exception:
        # The ack already went out; a failure to publish this notification
        # shouldn't fail the whole webhook request.
        logger.exception(
            "Failed to publish workout-complete event for session_id=%s day_number=%s",
            session_id, day_number,
        )


def _extract_session_and_day(text: str) -> tuple:
    session_match = _SESSION_ID_RE.search(text)
    day_match = _DAY_RE.search(text)
    if not session_match or not day_match:
        return None, None
    return int(session_match.group(1)), int(day_match.group(1))
