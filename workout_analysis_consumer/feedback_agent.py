"""The voice-feedback agent: turns what the client said (voice-note
transcripts after a workout, then her WhatsApp replies to the clarifying
questions) into structured coach notes for workout_comments and
user_joint_pain.

Claude only proposes notes (structured output); everything it returns is
checked here before it's stored: each note's quote must really appear in what
the client said, exercises must belong to the session and joints must be in
the joints table. Anything that fails is dropped rather than stored.
"""
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

import anthropic
from ai_usage import record_claude
from dotenv import load_dotenv
from pydantic import BaseModel

from workout_analysis_consumer.feedback_prompts import (
    EXTRACTION_SYSTEM_PROMPT,
    REPLY_MAPPING_SYSTEM_PROMPT,
)

load_dotenv()

logger = logging.getLogger(__name__)

# Same model as summarizer.py, so the consumer runs on one model.
MODEL = "claude-sonnet-5-5"

# Reads ANTHROPIC_API_KEY from the environment.
client = anthropic.Anthropic(
    max_retries=2,
    timeout=float(os.getenv("CLAUDE_REQUEST_TIMEOUT_SECONDS", "120")),
)

MAX_FOLLOW_UPS = 2

Category = Literal[
    "difficulty", "joint_pain", "pain_resolved", "discomfort",
    "fatigue", "technique", "enjoyment", "other",
]
Difficulty = Literal["too_easy", "about_right", "too_hard"]
PainLevel = Literal["mild", "moderate", "severe"]
# The joints lookup table's names (see CLAUDE.md). validate_note still checks
# them against the live table, so a joint added later is simply dropped until
# it's listed here.
JointName = Literal["ankle", "knee", "hip", "spine", "shoulder", "elbow", "wrist"]
QuestionTopic = Literal[
    "new_exercise", "too_easy", "too_hard", "joint_pain",
    "incomplete_sets", "discomfort", "other",
]

PAIN_RANK = {"mild": 1, "moderate": 2, "severe": 3}


class FeedbackRefusedError(RuntimeError):
    """Claude's safety classifiers declined the request (and no fallback
    model took it), so there's nothing to store."""


# --- Structured-output schemas ---------------------------------------------

class ExtractedNote(BaseModel):
    transcript_id: str
    session_exercise_id: Optional[int]
    category: Category
    difficulty: Optional[Difficulty]
    joint: Optional[JointName]
    pain_level: Optional[PainLevel]
    urgent: bool
    comment: str
    quote: str


class FeedbackExtraction(BaseModel):
    notes: List[ExtractedNote]


class ReplyNote(BaseModel):
    question_id: Optional[str]
    session_exercise_id: Optional[int]
    category: Category
    difficulty: Optional[Difficulty]
    joint: Optional[JointName]
    pain_level: Optional[PainLevel]
    urgent: bool
    comment: str
    quote: str


class AnswerSummary(BaseModel):
    question_id: str
    summary: str


class Question(BaseModel):
    text: str
    intent: str
    topic: QuestionTopic
    session_exercise_id: Optional[int]
    joint: Optional[JointName]


class ReplyMapping(BaseModel):
    answers: List[AnswerSummary]
    notes: List[ReplyNote]
    follow_ups: List[Question]


# --- Claude call ------------------------------------------------------------

def _parse(system: str, payload: Dict[str, Any], output_format, log_label: str, usage: Dict[str, Any]):
    user_content = json.dumps(payload, indent=2, default=str, ensure_ascii=False)
    logger.info("%s prompt\n--- user ---\n%s", log_label, user_content)
    response = client.beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user_content}],
        output_format=output_format,
        # On a policy decline, the API re-runs the request on Anthropic's
        # recommended fallback model within the same call.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    # Billed even when it refuses, so recorded first.
    record_claude(response, **usage)
    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise FeedbackRefusedError(f"Claude declined ({log_label}, category: {category})")
    if response.parsed_output is None:
        raise ValueError(f"No structured output for {log_label} (stop_reason={response.stop_reason})")
    return response.parsed_output


def _usage(context: Dict[str, Any], feature: str) -> Dict[str, Any]:
    """Who an ai_usage row is for."""
    return {"feature": feature, "user_id": context.get("user_id"), "session_id": context.get("session_id")}


@dataclass
class VoiceNote:
    """One transcribed voice note: the session's ("session") or one
    exercise's ("exercise_<session_exercise_id>")."""
    id: str
    source: str  # session_voice_note | exercise_voice_note
    session_exercise_id: Optional[int]
    exercise_name: Optional[str]
    text: str


def _exercises_for_prompt(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    keys = (
        "session_exercise_id", "name", "movement_type", "unit", "prescribed_sets",
        "prescribed_reps", "set_logs", "effort_flag", "is_new",
    )
    return [{key: exercise.get(key) for key in keys} for exercise in context.get("exercises", [])]


def extract_feedback(
    voice_notes: List[VoiceNote], context: Dict[str, Any], joints: Dict[str, int]
) -> List[Dict[str, Any]]:
    """Structured coach notes from the session's voice notes, validated
    (see validate_note). Each returned dict is a workout_comments row minus
    user_id/session_id."""
    if not voice_notes:
        return []
    extraction = _parse(
        EXTRACTION_SYSTEM_PROMPT,
        {
            "transcripts": [
                {
                    "id": note.id,
                    "source": note.source,
                    "session_exercise_id": note.session_exercise_id,
                    "exercise_name": note.exercise_name,
                    "text": note.text,
                }
                for note in voice_notes
            ],
            "exercises": _exercises_for_prompt(context),
            "joints": sorted(joints),
        },
        FeedbackExtraction,
        f"Feedback extraction for session_id={context.get('session_id')}",
        _usage(context, "feedback_extraction"),
    )
    by_id = {note.id: note for note in voice_notes}
    exercise_ids = exercise_id_map(context)
    rows = []
    for note in extraction.notes:
        voice_note = by_id.get(note.transcript_id)
        if voice_note is None:
            logger.warning("Dropping note for unknown transcript_id=%s", note.transcript_id)
            continue
        row = validate_note(
            note, voice_note.text, exercise_ids, joints,
            default_session_exercise_id=voice_note.session_exercise_id,
        )
        if row is not None:
            row["source"] = voice_note.source
            rows.append(row)
    return rows


def map_reply(
    questions: List[Dict[str, Any]],
    earlier_replies: List[str],
    new_reply: str,
    context: Dict[str, Any],
    joints: Dict[str, int],
    follow_ups_allowed: bool,
    question_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Map one WhatsApp reply onto the open questions.

    Returns {"answers": {question_id: summary}, "notes": [workout_comments
    rows minus user_id/session_id/source/reply id], "follow_ups": [question
    dicts]} — all validated.
    """
    mapping = _parse(
        REPLY_MAPPING_SYSTEM_PROMPT,
        {
            "questions": [
                {key: q.get(key) for key in ("id", "text", "intent", "session_exercise_id", "joint")}
                for q in questions
            ],
            "earlier_replies": earlier_replies,
            "new_reply": new_reply,
            "exercises": _exercises_for_prompt(context),
            "joints": sorted(joints),
            "current_joint_pain": context.get("joint_pain", []),
            "follow_ups_allowed": follow_ups_allowed,
            "previous_questions_and_answers": question_history or [],
        },
        ReplyMapping,
        f"Reply mapping for session_id={context.get('session_id')}",
        _usage(context, "reply_mapping"),
    )
    question_ids = {q["id"] for q in questions}
    questions_by_id = {q["id"]: q for q in questions}
    exercise_ids = exercise_id_map(context)

    answers = {
        answer.question_id: answer.summary.strip()
        for answer in mapping.answers
        if answer.question_id in question_ids and answer.summary.strip()
    }

    notes = []
    for note in mapping.notes:
        question_id = note.question_id if note.question_id in question_ids else None
        default_seid = (questions_by_id.get(question_id) or {}).get("session_exercise_id")
        row = validate_note(note, new_reply, exercise_ids, joints, default_session_exercise_id=default_seid)
        if row is not None:
            row["question_id"] = question_id
            notes.append(row)

    follow_ups = []
    if follow_ups_allowed:
        follow_ups = validate_questions(mapping.follow_ups, exercise_ids, joints, "f", MAX_FOLLOW_UPS)
    return {"answers": answers, "notes": notes, "follow_ups": follow_ups}


# --- Validation (pure) --------------------------------------------------------

_PUNCTUATION_RE = re.compile(r"[\s.,!?;:\"'“”‘’…\-()\[\]]+")


def _normalize(text: str) -> str:
    return _PUNCTUATION_RE.sub(" ", text.casefold()).strip()


def quote_in_text(quote: str, text: str) -> bool:
    """Whether quote really occurs in text, ignoring case, punctuation and
    spacing — the guard against notes the client never said."""
    normalized_quote = _normalize(quote)
    return bool(normalized_quote) and normalized_quote in _normalize(text)


def exercise_id_map(context: Dict[str, Any]) -> Dict[int, Optional[int]]:
    """session_exercise_id -> exercise_id for the session's exercises."""
    return {
        exercise["session_exercise_id"]: exercise.get("exercise_id")
        for exercise in context.get("exercises", [])
        if exercise.get("session_exercise_id") is not None
    }


def validate_note(
    note,
    source_text: str,
    exercise_ids: Dict[int, Optional[int]],
    joints: Dict[str, int],
    default_session_exercise_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """A workout_comments row (minus user_id/session_id/source) for one
    model-proposed note, or None if it can't be trusted: its quote isn't in
    what the client said, or it has no comment. An unknown exercise falls
    back to default_session_exercise_id (the exercise the voice note or
    question was about); an unknown joint is dropped, and a pain note with no
    known joint is kept as a comment only (it can't update user_joint_pain).
    """
    if not quote_in_text(note.quote, source_text):
        logger.warning("Dropping note whose quote isn't in the transcript: %r", note.quote)
        return None
    comment = (note.comment or "").strip()
    if not comment:
        return None

    session_exercise_id = note.session_exercise_id
    if session_exercise_id not in exercise_ids:
        session_exercise_id = (
            default_session_exercise_id if default_session_exercise_id in exercise_ids else None
        )

    joint_id = joints.get(note.joint) if note.joint else None
    category = note.category
    if category == "pain_resolved" and joint_id is None:
        # Nothing it could clear: keep what she said as a plain note.
        category = "other"
    return {
        "session_exercise_id": session_exercise_id,
        "exercise_id": exercise_ids.get(session_exercise_id) if session_exercise_id else None,
        "category": category,
        "difficulty": note.difficulty if category == "difficulty" else None,
        "joint_id": joint_id,
        "pain_level": (note.pain_level or "mild") if category == "joint_pain" else None,
        "urgent": bool(note.urgent),
        "comment": comment,
        "quote": note.quote.strip(),
    }


def joint_pain_changes(rows: List[Dict[str, Any]]) -> Dict[int, Optional[str]]:
    """joint_id -> new pain_level (or None to clear it) from one batch of
    notes. Within a batch the worst level mentioned wins, and a joint is
    cleared only if nothing in the batch says it still hurts. Across batches
    the caller simply applies each in turn, so the latest one overwrites."""
    levels: Dict[int, str] = {}
    resolved = set()
    for row in rows:
        joint_id = row.get("joint_id")
        if joint_id is None:
            continue
        if row["category"] == "joint_pain" and row.get("pain_level"):
            current = levels.get(joint_id)
            if current is None or PAIN_RANK[row["pain_level"]] > PAIN_RANK[current]:
                levels[joint_id] = row["pain_level"]
        elif row["category"] == "pain_resolved":
            resolved.add(joint_id)
    changes: Dict[int, Optional[str]] = {joint_id: None for joint_id in resolved}
    changes.update(levels)
    return changes


def validate_questions(
    questions: List[Question],
    exercise_ids: Dict[int, Optional[int]],
    joints: Dict[str, int],
    id_prefix: str,
    limit: int,
) -> List[Dict[str, Any]]:
    """Question dicts for session_clarifications.questions, with stable ids
    (q1, q2, … or f1, f2, …). Unknown exercises/joints are unlinked rather
    than kept, empty questions are dropped, only the first (most important)
    question about each exercise is kept, and at most `limit` are kept."""
    validated = []
    asked_about = set()
    for question in questions:
        text = (question.text or "").strip()
        if not text:
            continue
        session_exercise_id = (
            question.session_exercise_id if question.session_exercise_id in exercise_ids else None
        )
        if session_exercise_id is not None:
            if session_exercise_id in asked_about:
                continue
            asked_about.add(session_exercise_id)
        validated.append({
            "id": f"{id_prefix}{len(validated) + 1}",
            "text": text,
            "intent": question.intent.strip(),
            "topic": question.topic,
            "session_exercise_id": session_exercise_id,
            "joint": question.joint if question.joint in joints else None,
        })
        if len(validated) == limit:
            break
    return validated
