"""Dry run of the voice-feedback agent for one session: transcribe the voice
notes, run the extraction and the summary-and-questions calls, and print
every prompt and response. Nothing is written to the database, no voice note
is generated and nothing is sent on WhatsApp or Kafka.

Run (from the repo root):
    .venv/bin/python -m workout_analysis_consumer.dry_run --user-id 9715424567
    .venv/bin/python -m workout_analysis_consumer.dry_run --session-id 81
    ... --voice-out /path/to/summary.mp3   # also run Sarvam TTS, saved locally only

Costs real money: a Sarvam STT job per voice note and two Claude calls (and
one TTS call with --voice-out). The voice note is never uploaded or sent.
"""
import argparse
import json
import logging
import sys
from types import SimpleNamespace
from typing import Optional

from ai_usage import record_tts, set_feature_prefix
from workout_analysis_consumer import feedback_agent, main, summarizer
from workout_analysis_consumer.feedback_agent import exercise_id_map, extract_feedback, validate_questions
from workout_analysis_consumer.repository import AnalysisRepository
from workout_analysis_consumer.summarizer import generate_workout_summary, spoken_text

RULE = "=" * 100


def _section(title: str) -> None:
    print(f"\n{RULE}\n{title}\n{RULE}", flush=True)


def _dump(value) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


class _PrintingMessages:
    """Stands in for client.beta.messages: prints each parse() request and
    its response around the real call."""

    def __init__(self, real_messages, label: str):
        self._real = real_messages
        self._label = label

    def parse(self, **kwargs):
        _section(f"{self._label} — PROMPT (model={kwargs.get('model')})")
        print("--- system ---")
        print(kwargs.get("system"))
        for message in kwargs.get("messages", []):
            print(f"--- {message['role']} ---")
            print(message["content"])
        response = self._real.parse(**kwargs)
        _section(f"{self._label} — RESPONSE")
        print(f"stop_reason: {response.stop_reason}")
        usage = getattr(response, "usage", None)
        if usage is not None:
            print(f"usage: input_tokens={usage.input_tokens} output_tokens={usage.output_tokens}")
        parsed = response.parsed_output
        print(_dump(parsed.model_dump() if parsed is not None else None))
        return response


def _printing_client(real_client, label: str):
    return SimpleNamespace(beta=SimpleNamespace(messages=_PrintingMessages(real_client.beta.messages, label)))


def _latest_completed_session(repo: AnalysisRepository, user_id: str) -> Optional[int]:
    rows = (
        repo.client.table("sessions")
        .select("id, completed_at, plans!inner(user_id)")
        .eq("plans.user_id", user_id)
        .not_.is_("completed_at", "null")
        .order("completed_at", desc=True)
        .limit(1)
        .execute()
        .data
    )
    return rows[0]["id"] if rows else None


def run(session_id: int, voice_out: Optional[str] = None) -> None:
    repo = AnalysisRepository()
    context = repo.fetch_context(session_id)
    if context is None:
        sys.exit(f"No session {session_id}")
    _section(
        f"SESSION {session_id} — user {context['user_id']} ({context.get('client_name')}), "
        f"day {context['day_number']}, {context.get('workout_type', 'strength')}"
    )

    session_path = context.pop("feedback_audio_path", None)
    exercise_paths = context.pop("exercise_feedback_audio_paths", {}) or {}
    print(f"session voice note: {session_path or '-'}")
    print(f"exercise voice notes: {exercise_paths or '-'}")

    voice_notes = main._transcribe_voice_notes(context, session_path, exercise_paths)
    _section("TRANSCRIPTS")
    for note in voice_notes:
        print(f"[{note.id}] {note.exercise_name or 'whole session'}: {note.text}")
    if not voice_notes:
        print("(none)")

    joints = repo.list_joints()
    if voice_notes:
        rows = extract_feedback(voice_notes, context, joints)
        _section("VALIDATED NOTES (would go to workout_comments — NOT written)")
        print(_dump(rows))
        changes = feedback_agent.joint_pain_changes(rows)
        print(f"\nuser_joint_pain changes (NOT written): {changes or 'none'}")
        context["client_feedback_notes"] = [
            {key: row[key] for key in ("session_exercise_id", "category", "comment")} for row in rows
        ]
    else:
        _section("EXTRACTION skipped — no voice notes")

    history = repo.fetch_question_history(context["user_id"], session_id)
    if history:
        context["previous_questions_and_answers"] = history

    summary = generate_workout_summary(context)
    questions = validate_questions(
        summary.questions, exercise_id_map(context), joints, "q", main.MAX_QUESTIONS
    )
    names = {e["session_exercise_id"]: e["name"] for e in context.get("exercises", [])}

    _section(f"VALIDATED QUESTIONS ({len(questions)}) — would go to session_clarifications, NOT written")
    for question in questions:
        about = names.get(question["session_exercise_id"]) or question["joint"] or "-"
        print(f"{question['id']}  [{question['topic']}]  about: {about}")
        print(f"    {question['text']}")
        print(f"    intent: {question['intent']}")

    _section("SPOKEN TEXT (would go to TTS — NOT generated)")
    print(spoken_text(summary, questions))
    print(f"\n({len(spoken_text(summary, questions))} characters)")

    if voice_out:
        # Same TTS as workout_analysis_consumer.voice, minus the ogg
        # transcode and the upload: an mp3 plays anywhere.
        from tts import SarvamTTSClient
        tts_client = SarvamTTSClient()
        audio = tts_client.convert(spoken_text(summary, questions))
        record_tts(spoken_text(summary, questions), tts_client._model, "summary_tts",
                   user_id=context["user_id"], session_id=session_id)
        with open(voice_out, "wb") as f:
            f.write(audio)
        _section("VOICE NOTE (local only — not uploaded or sent)")
        print(f"{voice_out} ({len(audio)} bytes)")


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--user-id", help="use this user's most recently completed session")
    target.add_argument("--session-id", type=int)
    parser.add_argument("--voice-out", help="also run TTS and save the mp3 here (local only)")
    args = parser.parse_args()

    # Its calls are recorded in ai_usage like any other, tagged as a dry run.
    set_feature_prefix("dry_run_")
    # The prompts are printed below; keep the modules' own INFO logs quiet.
    logging.getLogger().setLevel(logging.WARNING)

    feedback_agent.client = _printing_client(feedback_agent.client, "EXTRACTION AGENT")
    summarizer.client = _printing_client(summarizer.client, "SUMMARY + QUESTIONS AGENT")

    session_id = args.session_id
    if session_id is None:
        session_id = _latest_completed_session(AnalysisRepository(), args.user_id)
        if session_id is None:
            sys.exit(f"No completed session for user {args.user_id}")
    run(session_id, args.voice_out)


if __name__ == "__main__":
    _main()
