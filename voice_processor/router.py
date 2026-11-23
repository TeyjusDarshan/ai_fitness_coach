"""The router: one WhatsApp message from a client (a voice note, or a text
without a "Session ID" line) -> the processor that should handle it.

1. Record the message in `inbound_messages` (one row per WhatsApp message
   id, so a redelivered message is handled once).
2. Find the client by her WhatsApp number (`user_profiles.whatsapp_number`).
3. A voice note is downloaded from WhatsApp, stored in the voice-feedback
   bucket and transcribed once with Sarvam; everything after this works
   from the transcript.
4. Work out which labels are possible: `question_reply` only while she has
   an open round of clarifying questions, `diet_checkin` only while the
   coach has diet tracking on for her, `other` always. When `other` is the
   only one, Claude isn't asked.
5. Claude Haiku picks one (voice_processor/router_agent.py); a refusal or
   failure counts as `other`.
6. Act on it: `question_reply` -> workout.process_reply (today's reply
   flow); `diet_checkin` -> a meal log (source `whatsapp`) run through the
   diet pipeline, then feedback on today's meals (meal_feedback.py: "on
   track", or what's off as a voice note with a tip), "Noted" for food from
   yesterday, or a Tamil "please send it again" when no food could be
   worked out; `other` -> nothing.

The Sarvam cost is recorded once the route is known, under the feature the
rest of that flow uses (`meal_stt` / `reply_stt`), or `inbound_stt`.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ai_usage import record_stt
from diet.dates import now_in, today_in
from diet.pipeline import process_meal_log
from diet.repository import DietRepository
from diet.transcription import transcribe_audio_unrecorded
from voice_processor import meal_feedback, router_agent, workout
from voice_processor.feedback import audio_extension, store_reply_audio
from voice_processor.repository import AnalysisRepository
from voice_processor.router_agent import DIET_CHECKIN, OTHER, QUESTION_REPLY

logger = logging.getLogger(__name__)

NOTED_MESSAGE = "Noted"
# Sent when a message routed as a diet check-in had no food we could log.
DIET_RETRY_MESSAGE = "மன்னிக்கவும், நீங்க சாப்பிட்டது புரியல. மறுபடியும் அனுப்புங்க 🙏"

# A meal reminder sent this recently is shown to the router.
REMINDER_HINT_HOURS = 3

STT_FEATURES = {DIET_CHECKIN: "meal_stt", QUESTION_REPLY: "reply_stt", OTHER: "inbound_stt"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def allowed_labels(has_open_questions: bool, diet_enabled: bool) -> List[str]:
    labels = []
    if diet_enabled:
        labels.append(DIET_CHECKIN)
    if has_open_questions:
        labels.append(QUESTION_REPLY)
    return labels + [OTHER]


def _minutes_since(asked_at: Optional[str]) -> Optional[int]:
    if not asked_at:
        return None
    try:
        return max(0, int((datetime.now(timezone.utc) - datetime.fromisoformat(asked_at)).total_seconds() // 60))
    except (TypeError, ValueError):
        return None


def decide(
    message: str, message_type: str, labels: List[str], clarification: Optional[Dict[str, Any]], user_id: str,
    meal_reminder: Optional[Dict[str, Any]] = None, timezone_name: Optional[str] = None,
) -> Dict[str, Any]:
    """{label, day, reason, model} for one message."""
    if labels == [OTHER]:
        return {"label": OTHER, "day": "today", "reason": "No open questions and diet tracking is off.", "model": None}
    payload = router_agent.build_payload(
        message, message_type, labels, now_in(timezone_name),
        open_questions=(clarification or {}).get("questions") if clarification else None,
        minutes_since_asked=_minutes_since((clarification or {}).get("asked_at")),
        meal_reminder=meal_reminder if DIET_CHECKIN in labels else None,
    )
    try:
        decision = router_agent.classify_message(payload, user_id=user_id)
    except Exception as error:
        logger.exception("Routing failed for user_id=%s; treating the message as other", user_id)
        return {"label": OTHER, "day": "today", "reason": f"Routing failed: {error}", "model": router_agent.ROUTER_MODEL}
    label = decision.label if decision.label in labels else OTHER
    return {"label": label, "day": decision.day, "reason": decision.reason, "model": router_agent.ROUTER_MODEL}


def _recent_reminder(repo: AnalysisRepository, user_id: str) -> Optional[Dict[str, Any]]:
    """{asked_about, minutes_ago} of a meal reminder (meal_reminders.py) sent
    to her in the last REMINDER_HINT_HOURS, or None. Best-effort."""
    try:
        reminder = repo.recent_meal_reminder(
            user_id, datetime.now(timezone.utc) - timedelta(hours=REMINDER_HINT_HOURS)
        )
    except Exception:
        logger.exception("Failed to look up a recent meal reminder for user_id=%s", user_id)
        return None
    if not reminder:
        return None
    return {"asked_about": reminder.get("missing_meals") or [], "minutes_ago": _minutes_since(reminder.get("sent_at"))}


def _transcribe(repo: AnalysisRepository, inbound: Dict[str, Any], media_id: Optional[str]):
    """Download, store and transcribe a voice note -> (transcript, stt) where
    stt is (audio, file name, model) for recording its cost later, or None
    when it was already transcribed (a redelivered message)."""
    if inbound.get("transcript") is not None:
        return inbound["transcript"], None
    audio, mime_type = workout.whatsapp_client.download_media(media_id)
    path = f"inbound_{inbound['id']}.{audio_extension(mime_type)}"
    store_reply_audio(audio, path, mime_type.split(";")[0].strip())
    transcript, model = transcribe_audio_unrecorded(audio, path)
    transcript = (transcript or "").strip()
    repo.update_inbound(inbound["id"], {"audio_path": path, "transcript": transcript})
    inbound["audio_path"] = path
    return transcript, (audio, path, model)


def _send_text(phone_number: str, body: str) -> None:
    try:
        workout.whatsapp_client.send_text(phone_number, body)
    except Exception:
        logger.exception("Failed to send WhatsApp text to %s", phone_number)


def log_meal(
    diet_repo: DietRepository, user_id: str, phone_number: str, transcript: str,
    audio_path: Optional[str], day: str, timezone_name: Optional[str] = None,
) -> int:
    """A WhatsApp diet check-in -> a meal log worked out by the diet
    pipeline (from the router's transcript, no second download), then
    feedback on today's meals (falling back to "Noted" if that fails),
    "Noted" for yesterday's food, or a request to send it again when no
    food was found."""
    # Her own calendar day (user_profiles.timezone), not India's.
    logged_for = today_in(timezone_name) - timedelta(days=1 if day == "yesterday" else 0)
    log = diet_repo.create_meal_log(user_id, logged_for, source="whatsapp")
    if audio_path:
        diet_repo.update_meal_log(log["id"], {"audio_path": audio_path})
    process_meal_log(diet_repo, log["id"], lambda _log: transcript)
    status = (diet_repo.get_meal_log(log["id"]) or {}).get("status")
    if status != "ready":
        _send_text(phone_number, DIET_RETRY_MESSAGE)
    elif day == "yesterday":
        _send_text(phone_number, NOTED_MESSAGE)
    else:
        try:
            meal_feedback.send_feedback(
                diet_repo, workout.whatsapp_client, log["id"], user_id, phone_number, timezone_name,
            )
        except Exception:
            logger.exception("Meal feedback failed for meal_log_id=%s; sending Noted", log["id"])
            _send_text(phone_number, NOTED_MESSAGE)
    logger.info("WhatsApp diet check-in for user_id=%s -> meal_log_id=%s (%s)", user_id, log["id"], status)
    return log["id"]


def handle_inbound(workout_repo: AnalysisRepository, diet_repo: DietRepository, payload: Dict[str, Any]) -> None:
    phone_number = payload["phone_number"]
    message_type = payload.get("type", "text")
    profile = workout_repo.get_profile_for_routing(phone_number)
    user_id = profile["user_id"] if profile else None

    inbound = workout_repo.get_or_create_inbound({
        "whatsapp_message_id": payload["whatsapp_message_id"],
        "phone_number": phone_number,
        "user_id": user_id,
        "message_type": message_type,
        "text": payload.get("text"),
        "media_id": payload.get("media_id"),
    })
    if inbound.get("handled_at"):
        logger.info("Message %s already handled; skipping", payload["whatsapp_message_id"])
        return

    def finish(route: str, reason: str, model: Optional[str] = None, **fields: Any) -> None:
        workout_repo.update_inbound(inbound["id"], {
            "route": route, "route_reason": reason, "route_model": model,
            "routed_at": _now(), "handled_at": _now(), **fields,
        })

    if profile is None:
        logger.info("Message from unknown number %s; ignoring", phone_number)
        return finish(OTHER, "Unknown sender.")

    stt = None
    if message_type == "audio":
        message, stt = _transcribe(workout_repo, inbound, payload.get("media_id"))
    else:
        message = (payload.get("text") or "").strip()

    def record_transcription(route: str) -> None:
        if stt:
            audio, file_name, model = stt
            record_stt(audio, file_name, model, STT_FEATURES[route], user_id=user_id)

    if not message:
        record_transcription(OTHER)
        return finish(OTHER, "Nothing was said.")

    clarification = workout_repo.find_open_clarification(phone_number)
    labels = allowed_labels(clarification is not None, bool(profile.get("diet_enabled")))
    timezone_name = profile.get("timezone")
    decision = decide(
        message, message_type, labels, clarification, user_id,
        _recent_reminder(workout_repo, user_id), timezone_name,
    )
    route = decision["label"]
    record_transcription(route)
    workout_repo.update_inbound(inbound["id"], {
        "route": route, "route_reason": decision["reason"], "route_model": decision["model"], "routed_at": _now(),
    })
    logger.info("Routed message %s from user_id=%s as %s: %s",
                payload["whatsapp_message_id"], user_id, route, decision["reason"])

    fields: Dict[str, Any] = {}
    if route == QUESTION_REPLY:
        workout.process_reply(
            workout_repo, clarification, phone_number, payload["whatsapp_message_id"],
            message_type, message, inbound.get("audio_path"),
        )
        fields["clarification_id"] = clarification["id"]
    elif route == DIET_CHECKIN:
        fields["meal_log_id"] = log_meal(
            diet_repo, user_id, phone_number, message, inbound.get("audio_path"), decision["day"], timezone_name,
        )
    workout_repo.update_inbound(inbound["id"], {"handled_at": _now(), **fields})
