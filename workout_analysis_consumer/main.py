"""Consumer for workout-complete-events -> Tanglish workout-day summary plus
clarifying questions, and for workout-feedback-replies -> the client's
answers to those questions.

Run (from the repo root):  python3 -m workout_analysis_consumer.main
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from whatsapp_client import WhatsAppClient
from workout_analysis_consumer.consumer import (
    FEEDBACK_REPLY_TOPIC,
    WORKOUT_COMPLETE_TOPIC,
    build_consumer,
)
from workout_analysis_consumer.feedback import (
    store_reply_audio,
    transcribe_audio,
    transcribe_many,
)
from workout_analysis_consumer.feedback_agent import (
    VoiceNote,
    exercise_id_map,
    extract_feedback,
    joint_pain_changes,
    map_reply,
    validate_questions,
)
from workout_analysis_consumer.kafka_producer import KafkaProducerClient
from workout_analysis_consumer.repository import AnalysisRepository
from workout_analysis_consumer.summarizer import generate_workout_summary, spoken_text
from workout_analysis_consumer.voice import generate_voice_note

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

producer = KafkaProducerClient()
whatsapp_client = WhatsAppClient()

MAX_QUESTIONS = 10

# Fixed (not LLM-written) messages for the reply flow.
FOLLOW_UP_INTRO = "நன்றி! இன்னும் ஒரு சில விஷயம் தெரிஞ்சுக்கணும்."
FOLLOW_UP_CLOSING = "Voice note-ஆ இல்ல message-ஆ reply பண்ணுங்க."
THANK_YOU_MESSAGE = (
    "நன்றி! உங்க பதில்களை note பண்ணிட்டோம். "
    "அடுத்த workout-ல தேவையான மாற்றங்கள் பண்ணிடலாம் 💪"
)

# WhatsApp voice notes are audio/ogg (opus); the extension tells Sarvam the format.
_AUDIO_EXTENSIONS = {"audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp4": "m4a", "audio/aac": "aac", "audio/amr": "amr"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _transcribe_voice_notes(
    context: Dict[str, Any], session_path: Optional[str], exercise_paths: Dict[int, str]
) -> List[VoiceNote]:
    """Transcribe the session's and each exercise's voice notes (in
    parallel, each best-effort), and fold the transcripts into context for
    the summary."""
    paths: Dict[Any, str] = {}
    if session_path:
        paths["session"] = session_path
    for session_exercise_id, path in exercise_paths.items():
        paths[session_exercise_id] = path
    if not paths:
        logger.info("No voice feedback recorded for session_id=%s", context["session_id"])
        return []

    transcripts = transcribe_many(paths, _usage(context, "voice_note_stt"))
    notes = []
    if "session" in transcripts:
        context["client_voice_feedback"] = transcripts["session"]
        notes.append(VoiceNote("session", "session_voice_note", None, None, transcripts["session"]))
    for exercise in context.get("exercises", []):
        text = transcripts.get(exercise.get("session_exercise_id"))
        if text:
            exercise["client_voice_note"] = text
            notes.append(VoiceNote(
                f"exercise_{exercise['session_exercise_id']}", "exercise_voice_note",
                exercise["session_exercise_id"], exercise["name"], text,
            ))
    return notes


def _store_notes(
    repo: AnalysisRepository, user_id: str, session_id: int, rows: List[Dict[str, Any]], replace: bool,
    reply_id: Optional[int] = None,
) -> None:
    for row in rows:
        if row.get("urgent"):
            logger.warning(
                "URGENT client feedback for user_id=%s session_id=%s: %s", user_id, session_id, row["comment"]
            )
        if reply_id is not None:
            row["source"] = "clarification_reply"
            row["clarification_reply_id"] = reply_id
    if replace:
        repo.replace_voice_note_comments(user_id, session_id, rows)
    else:
        repo.insert_comments(user_id, session_id, rows)
    changes = joint_pain_changes(rows)
    if changes:
        repo.apply_joint_pain(user_id, changes)
        logger.info("Updated joint pain for user_id=%s: %s", user_id, changes)


def _process_message(repo: AnalysisRepository, session_id: int, phone_number: str) -> None:
    context = repo.fetch_context(session_id)
    if context is None:
        logger.warning("No session found for session_id=%s; skipping", session_id)
        return
    day_number = context["day_number"]
    user_id = context["user_id"]

    # Storage paths are for transcription only, never sent to the LLM.
    session_path = context.pop("feedback_audio_path", None)
    exercise_paths = context.pop("exercise_feedback_audio_paths", {}) or {}
    voice_notes = _transcribe_voice_notes(context, session_path, exercise_paths)

    joints = repo.list_joints()
    # Best-effort: a failed extraction shouldn't block the summary.
    if voice_notes:
        try:
            rows = extract_feedback(voice_notes, context, joints)
            _store_notes(repo, user_id, session_id, rows, replace=True)
            context["client_feedback_notes"] = [
                {key: row[key] for key in ("session_exercise_id", "category", "comment")} for row in rows
            ]
            logger.info("Stored %d voice-note comments for session_id=%s", len(rows), session_id)
        except Exception:
            logger.exception("Failed to extract voice feedback for session_id=%s", session_id)

    # Best-effort: without it the questions just can't refer back.
    try:
        history = repo.fetch_question_history(user_id, session_id)
        if history:
            context["previous_questions_and_answers"] = history
    except Exception:
        logger.exception("Failed to fetch question history for session_id=%s", session_id)

    summary = generate_workout_summary(context)
    questions = validate_questions(
        summary.questions, exercise_id_map(context), joints, "q", MAX_QUESTIONS
    )
    analysis = spoken_text(summary, questions)

    # Best-effort: a TTS/storage failure shouldn't discard the (costlier)
    # LLM-generated text analysis, so it's still saved with audio_url unset.
    try:
        audio_url = generate_voice_note(
            analysis, context["plan_id"], day_number, usage=_usage(context, "summary_tts")
        )
    except Exception:
        logger.exception(
            "Failed to generate voice note for session_id=%s day_number=%s", session_id, day_number
        )
        audio_url = None

    repo.save_analysis(session_id, analysis, audio_url)
    logger.info("Stored analysis for session_id=%s day_number=%s", session_id, day_number)

    # Opened before the voice note goes out, so a quick reply finds it.
    if questions:
        try:
            repo.supersede_open_clarifications(phone_number, session_id)
            repo.save_clarification(session_id, user_id, phone_number, 1, questions)
        except Exception:
            logger.exception("Failed to save clarifying questions for session_id=%s", session_id)

    # Best-effort: the analysis is already durably saved, so a failure to
    # send the WhatsApp reply shouldn't discard any of the above work.
    sent_audio = False
    if audio_url:
        try:
            whatsapp_client.send_audio(phone_number, audio_url)
            sent_audio = True
        except Exception:
            logger.exception(
                "Failed to send WhatsApp voice note for session_id=%s day_number=%s",
                session_id, day_number,
            )
    if questions and not sent_audio:
        # The questions still need to reach her, so fall back to text.
        _send_text(phone_number, _questions_text(summary.questions_intro, questions, summary.closing))

    # Best-effort: the analysis is already durably saved, so a failure to
    # publish this notification shouldn't fail the whole message.
    try:
        producer.send_workout_analysis_complete_event(user_id, session_id, day_number)
    except Exception:
        logger.exception(
            "Failed to publish workout-analysis-complete event for session_id=%s day_number=%s",
            session_id, day_number,
        )


def _questions_text(intro: str, questions: List[Dict[str, Any]], closing: str) -> str:
    lines = [intro.strip(), ""] + [f"{i}. {q['text']}" for i, q in enumerate(questions, 1)]
    return "\n".join(lines + ["", closing.strip()]).strip()


def _send_text(phone_number: str, body: str) -> None:
    try:
        whatsapp_client.send_text(phone_number, body)
    except Exception:
        logger.exception("Failed to send WhatsApp text to %s", phone_number)


def _usage(context: Dict[str, Any], feature: str) -> Dict[str, Any]:
    """Who an ai_usage row (speech-to-text / text-to-speech cost) is for."""
    return {"feature": feature, "user_id": context.get("user_id"), "session_id": context.get("session_id")}


def _transcribe_voice_reply(
    reply: Dict[str, Any], clarification: Dict[str, Any], media_id: str
) -> Dict[str, Any]:
    """Download a voice reply from WhatsApp, keep it in the voice-feedback
    bucket and transcribe it. Returns the clarification_replies fields."""
    audio, mime_type = whatsapp_client.download_media(media_id)
    content_type = mime_type.split(";")[0].strip()
    extension = _AUDIO_EXTENSIONS.get(content_type, "ogg")
    path = store_reply_audio(
        audio, f"session_{clarification['session_id']}_reply_{reply['id']}.{extension}", content_type
    )
    usage = {"feature": "reply_stt", "user_id": clarification["user_id"], "session_id": clarification["session_id"]}
    return {"audio_path": path, "transcript": (transcribe_audio(audio, path, usage) or "").strip()}


def _process_reply(repo: AnalysisRepository, payload: Dict[str, Any]) -> None:
    """Map one WhatsApp reply onto the open clarifying questions, store what
    it says, and answer: follow-up questions, a thank-you once everything is
    answered, or nothing while answers are still coming in."""
    phone_number = payload["phone_number"]
    clarification = repo.find_open_clarification(phone_number)
    if clarification is None:
        logger.info("No open questions for %s; ignoring reply %s", phone_number, payload.get("whatsapp_message_id"))
        return
    reply = repo.record_reply(
        clarification["id"], payload["whatsapp_message_id"], payload.get("type", "text"), payload.get("text")
    )
    if reply is None:
        logger.info("Reply %s already processed; skipping", payload["whatsapp_message_id"])
        return

    if payload.get("type") == "audio":
        fields = _transcribe_voice_reply(reply, clarification, payload["media_id"])
        repo.update_reply(reply["id"], fields)
        reply_text = fields["transcript"]
    else:
        reply_text = (payload.get("text") or "").strip()
    if not reply_text:
        repo.update_reply(reply["id"], {"processed_at": _now()})
        return

    session_id = clarification["session_id"]
    user_id = clarification["user_id"]
    context = repo.fetch_context(session_id) or {"session_id": session_id, "exercises": []}
    context.pop("feedback_audio_path", None)
    context.pop("exercise_feedback_audio_paths", None)
    joints = repo.list_joints()
    questions = clarification["questions"] or []

    follow_ups_allowed = clarification["round"] == 1
    history: List[Dict[str, Any]] = []
    if follow_ups_allowed:
        try:
            history = repo.fetch_question_history(user_id, session_id)
        except Exception:
            logger.exception("Failed to fetch question history for session_id=%s", session_id)

    mapping = map_reply(
        questions,
        repo.list_processed_reply_texts(clarification["id"]),
        reply_text,
        context,
        joints,
        follow_ups_allowed=follow_ups_allowed,
        question_history=history,
    )
    _store_notes(repo, user_id, session_id, mapping["notes"], replace=False, reply_id=reply["id"])

    answers = dict(clarification.get("answers") or {})
    for question_id, summary in mapping["answers"].items():
        answers[question_id] = {"summary": summary, "reply_id": reply["id"]}
    all_answered = all(q["id"] in answers for q in questions)

    follow_ups = mapping["follow_ups"]
    if follow_ups:
        repo.update_clarification(clarification["id"], {
            "answers": answers,
            "status": "answered" if all_answered else "superseded",
            "closed_at": _now(),
        })
        repo.save_clarification(session_id, user_id, phone_number, 2, follow_ups)
        _send_follow_ups(phone_number, context, follow_ups)
    elif all_answered:
        repo.update_clarification(clarification["id"], {
            "answers": answers, "status": "answered", "closed_at": _now(),
        })
        _send_text(phone_number, THANK_YOU_MESSAGE)
    else:
        repo.update_clarification(clarification["id"], {"answers": answers})

    repo.update_reply(reply["id"], {"processed_at": _now()})
    logger.info(
        "Processed reply %s for session_id=%s: %d answers, %d notes, %d follow-ups",
        payload["whatsapp_message_id"], session_id, len(mapping["answers"]), len(mapping["notes"]), len(follow_ups),
    )


def _send_follow_ups(phone_number: str, context: Dict[str, Any], follow_ups: List[Dict[str, Any]]) -> None:
    text = " ".join([FOLLOW_UP_INTRO] + [q["text"] for q in follow_ups] + [FOLLOW_UP_CLOSING])
    try:
        audio_url = generate_voice_note(
            text, context["plan_id"], context["day_number"], suffix="_followup",
            usage=_usage(context, "follow_up_tts"),
        )
        whatsapp_client.send_audio(phone_number, audio_url)
    except Exception:
        logger.exception("Failed to send follow-up voice note to %s; sending text", phone_number)
        _send_text(phone_number, _questions_text(FOLLOW_UP_INTRO, follow_ups, FOLLOW_UP_CLOSING))


def run() -> None:
    consumer = build_consumer()
    repo = AnalysisRepository()
    consumer.subscribe([WORKOUT_COMPLETE_TOPIC, FEEDBACK_REPLY_TOPIC])
    logger.info("Listening on topics=%s", [WORKOUT_COMPLETE_TOPIC, FEEDBACK_REPLY_TOPIC])

    try:
        while True:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                logger.error("Kafka consume error: %s", msg.error())
                continue

            # Best-effort: commit every message once attempted, success or
            # not, so one bad/unprocessable message can't wedge the
            # partition and block everything after it. Failures are logged
            # for manual follow-up rather than retried automatically.
            try:
                payload = json.loads(msg.value())
                if msg.topic() == FEEDBACK_REPLY_TOPIC:
                    _process_reply(repo, payload)
                else:
                    _process_message(repo, payload["session_id"], payload["phone_number"])
            except Exception:
                logger.exception(
                    "Failed to process message at topic=%s offset=%s partition=%s",
                    msg.topic(), msg.offset(), msg.partition(),
                )
            finally:
                consumer.commit(msg)
    finally:
        consumer.close()


if __name__ == "__main__":
    run()
