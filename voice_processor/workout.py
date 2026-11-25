"""The workout side of the voice processor (voice_processor/main.py):

- handle_workout_complete (the `summarizer` target): a shared workout ->
  the client's voice notes transcribed, coach notes extracted, and a
  Tanglish summary with clarifying questions sent back as a voice note.
- process_reply (called by the router, voice_processor/router.py, for a
  message it classified as `question_reply`): her WhatsApp answer to those
  questions, mapped onto them, with follow-ups when needed.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from whatsapp_client import WhatsAppClient
from voice_processor.feedback import transcribe_many
from voice_processor.feedback_agent import (
    VoiceNote,
    exercise_id_map,
    extract_feedback,
    joint_pain_changes,
    map_reply,
    validate_questions,
)
from voice_processor.kafka_producer import KafkaProducerClient
from voice_processor.repository import AnalysisRepository
from voice_processor.summarizer import generate_workout_summary, spoken_text
from voice_processor.voice import generate_voice_note

logger = logging.getLogger(__name__)

producer = KafkaProducerClient()
whatsapp_client = WhatsAppClient()

# The summary asks at most this many questions (most important first).
MAX_QUESTIONS = 3

# Fixed (not LLM-written) messages for the reply flow.
FOLLOW_UP_INTRO = "நன்றி! இன்னும் ஒரு சில விஷயம் தெரிஞ்சுக்கணும்."
THANK_YOU_MESSAGE = (
    "நன்றி! உங்க பதில்களை note பண்ணிட்டோம். "
    "அடுத்த workout-ல தேவையான மாற்றங்கள் பண்ணிடலாம் 💪"
)


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
        _send_text(phone_number, _questions_text(summary.summary, questions))

    # Best-effort: the analysis is already durably saved, so a failure to
    # publish this notification shouldn't fail the whole message.
    try:
        producer.send_workout_analysis_complete_event(user_id, session_id, day_number)
    except Exception:
        logger.exception(
            "Failed to publish workout-analysis-complete event for session_id=%s day_number=%s",
            session_id, day_number,
        )


def _questions_text(intro: str, questions: List[Dict[str, Any]]) -> str:
    lines = [intro.strip(), ""] + [f"{i}. {q['text']}" for i, q in enumerate(questions, 1)]
    return "\n".join(lines).strip()


def _send_text(phone_number: str, body: str) -> None:
    try:
        whatsapp_client.send_text(phone_number, body)
    except Exception:
        logger.exception("Failed to send WhatsApp text to %s", phone_number)


def _usage(context: Dict[str, Any], feature: str) -> Dict[str, Any]:
    """Who an ai_usage row (speech-to-text / text-to-speech cost) is for."""
    return {"feature": feature, "user_id": context.get("user_id"), "session_id": context.get("session_id")}


def process_reply(
    repo: AnalysisRepository,
    clarification: Dict[str, Any],
    phone_number: str,
    whatsapp_message_id: str,
    message_type: str,
    reply_text: str,
    audio_path: Optional[str] = None,
) -> None:
    """Map one WhatsApp reply onto her open round of questions
    (`clarification`), store what it says, and answer: follow-up questions,
    a thank-you once everything is answered, or nothing while answers are
    still coming in.

    The router (voice_processor/router.py) has already found the round,
    downloaded and stored a voice reply (`audio_path`) and transcribed it,
    so `reply_text` is the transcript or the typed text."""
    reply = repo.record_reply(
        clarification["id"], whatsapp_message_id, message_type, reply_text if message_type == "text" else None
    )
    if reply is None:
        logger.info("Reply %s already processed; skipping", whatsapp_message_id)
        return
    if message_type == "audio":
        repo.update_reply(reply["id"], {"audio_path": audio_path, "transcript": reply_text})
    reply_text = (reply_text or "").strip()
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
        whatsapp_message_id, session_id, len(mapping["answers"]), len(mapping["notes"]), len(follow_ups),
    )


def _send_follow_ups(phone_number: str, context: Dict[str, Any], follow_ups: List[Dict[str, Any]]) -> None:
    text = " ".join([FOLLOW_UP_INTRO] + [q["text"] for q in follow_ups])
    try:
        audio_url = generate_voice_note(
            text, context["plan_id"], context["day_number"], suffix="_followup",
            usage=_usage(context, "follow_up_tts"),
        )
        whatsapp_client.send_audio(phone_number, audio_url)
    except Exception:
        logger.exception("Failed to send follow-up voice note to %s; sending text", phone_number)
        _send_text(phone_number, _questions_text(FOLLOW_UP_INTRO, follow_ups))


def handle_workout_complete(repo: AnalysisRepository, payload: Dict[str, Any]) -> None:
    _process_message(repo, payload["session_id"], payload["phone_number"])

