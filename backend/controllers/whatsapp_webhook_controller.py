"""Webhook for the WhatsApp Business (Cloud API) account the coach shares
with clients (see COACH_WHATSAPP_NUMBER in frontend/src/constants.ts).

Meta forwards every inbound message on that number here as a POST. The
"Share Session with Coach" button (frontend/src/utils.ts:buildCoachShareMessage)
embeds "Session ID: <id>" / "Day: <n>" lines in the shared text, so a message
carrying a session id (a sessions row — one training day of a plan) is
treated as a workout-complete trigger: we ack it
immediately, then publish a workout-complete event so
workout_analysis_consumer can generate the analysis/voice note and push it
back to the sender once it's ready. That voice note ends with a few
clarifying questions, so any other text or voice message is published as a
workout-feedback-replies event for the consumer to match against the
sender's open questions (it ignores messages from anyone with none open).
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

# Matches the "Session ID: <id>" line added in
# frontend/src/utils.ts:buildCoachShareMessage. (Its "Day: <n>" line is just
# for the coach to read — the session row already knows its day.)
_SESSION_ID_RE = re.compile(r"Session ID:\s*(\d+)")

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
    if not sender:
        return
    if message.get("type") == "audio":
        _publish_reply(sender, message, {"type": "audio", "media_id": (message.get("audio") or {}).get("id")})
        return
    text = (message.get("text") or {}).get("body", "")
    if not text:
        return

    match = _SESSION_ID_RE.search(text)
    if not match:
        _publish_reply(sender, message, {"type": "text", "text": text})
        return
    session_id = int(match.group(1))

    try:
        whatsapp_client.send_text(sender, WORKOUT_RECEIVED_MESSAGE)
    except Exception:
        logger.exception("Failed to send WhatsApp ack to %s", sender)

    try:
        kafka_producer.send_workout_complete_event(session_id, sender)
    except Exception:
        # The ack already went out; a failure to publish this notification
        # shouldn't fail the whole webhook request.
        logger.exception("Failed to publish workout-complete event for session_id=%s", session_id)


def _publish_reply(sender: str, message: dict, content: dict) -> None:
    """Forward a possible answer to the clarifying questions to the consumer."""
    message_id = message.get("id")
    if not message_id or (content["type"] == "audio" and not content.get("media_id")):
        logger.info("Ignoring WhatsApp message from %s with no id/media", sender)
        return
    try:
        kafka_producer.send_feedback_reply_event(
            {"phone_number": sender, "whatsapp_message_id": message_id, **content}
        )
    except Exception:
        logger.exception("Failed to publish feedback-reply event for message %s", message_id)
