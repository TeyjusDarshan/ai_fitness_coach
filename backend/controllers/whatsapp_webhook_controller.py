"""Webhook for the WhatsApp Business (Cloud API) account the coach shares
with clients (see COACH_WHATSAPP_NUMBER in frontend/src/constants.ts).

Meta forwards every inbound message on that number here as a POST. Each one
is published to the single `user-conversation` Kafka topic, tagged with the
voice processor's processor that should handle it (`target`):

- text with a "Session ID: <id>" line (the "Share Session with Coach"
  button, frontend/src/utils.ts:buildCoachShareMessage) is a shared
  workout: we ack it immediately and tag it `summarizer`, which writes the
  analysis voice note and its clarifying questions. Decided by this rule
  alone, never by a model.
- every voice note, and any other text, is tagged `router`: the voice
  processor downloads and transcribes it, and Claude Haiku decides whether
  it answers her open questions, is a diet check-in, or neither
  (voice_processor/router.py).

Every inbound message (any type) also updates `whatsapp_conversations`, the
client's last-message time, which decides whether WhatsApp's 24-hour
free-form reply window is open (see backend/repository/whatsapp_repository.py).
"""
import logging
import os
import re

from flask import Blueprint, jsonify, request

from backend.kafka_producer import TARGET_ROUTER, TARGET_SUMMARIZER, KafkaProducerClient
from backend.repository.whatsapp_repository import WhatsAppRepository, message_time
from whatsapp_client import WhatsAppClient

logger = logging.getLogger(__name__)

whatsapp_webhook_bp = Blueprint("whatsapp_webhook", __name__)

whatsapp_client = WhatsAppClient()
kafka_producer = KafkaProducerClient()
whatsapp_repo = WhatsAppRepository()

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
    _record_inbound(sender, message)
    if message.get("type") == "audio":
        _publish_to_router(sender, message, {"type": "audio", "media_id": (message.get("audio") or {}).get("id")})
        return
    text = (message.get("text") or {}).get("body", "")
    if not text:
        return

    match = _SESSION_ID_RE.search(text)
    if not match:
        _publish_to_router(sender, message, {"type": "text", "text": text})
        return
    session_id = int(match.group(1))

    try:
        whatsapp_client.send_text(sender, WORKOUT_RECEIVED_MESSAGE)
    except Exception:
        logger.exception("Failed to send WhatsApp ack to %s", sender)

    try:
        delivered = kafka_producer.send_user_conversation_event(
            TARGET_SUMMARIZER, {"session_id": session_id, "phone_number": sender}, key=sender
        )
        if not delivered:
            logger.error("Workout-complete event for session_id=%s was not delivered", session_id)
    except Exception:
        # The ack already went out; a failure to publish this notification
        # shouldn't fail the whole webhook request.
        logger.exception("Failed to publish workout-complete event for session_id=%s", session_id)


def _publish_to_router(sender: str, message: dict, content: dict) -> None:
    """Hand a voice note or a plain text to the voice processor's router."""
    message_id = message.get("id")
    if not message_id or (content["type"] == "audio" and not content.get("media_id")):
        logger.info("Ignoring WhatsApp message from %s with no id/media", sender)
        return
    try:
        delivered = kafka_producer.send_user_conversation_event(
            TARGET_ROUTER, {"phone_number": sender, "whatsapp_message_id": message_id, **content}, key=sender
        )
        if not delivered:
            logger.error("Router event for message %s was not delivered", message_id)
    except Exception:
        logger.exception("Failed to publish router event for message %s", message_id)


def _record_inbound(sender: str, message: dict) -> None:
    """Note when she last messaged (any type of message opens WhatsApp's
    24-hour reply window). Best-effort: never blocks handling the message."""
    try:
        whatsapp_repo.record_inbound(sender, message_time(message), message.get("id"), message.get("type") or "unknown")
    except Exception:
        logger.exception("Failed to record the WhatsApp reply window for %s", sender)
