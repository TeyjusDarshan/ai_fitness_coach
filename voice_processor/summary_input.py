"""The workout summary's user message (summarizer.generate_workout_summary):
the context from AnalysisRepository.fetch_context rendered as plain text
instead of JSON, with the question history grouped into topic threads.

Same facts, fewer tokens. Tested on 20 real sessions on 2026-11-25 (input
-33%, cost -14%, question quality unchanged; see the Obsidian note
"Workout Summary Token Experiment 2026-11-25"). JSON spends most of its
tokens on quotes, braces, indentation and repeated keys, and the history
repeats each question's Tamil wording next to its English intent.

- Every field keeps the name WORKOUT_ANALYSIS_SYSTEM_PROMPT uses for it.
- One line per exercise, starting with its session_exercise_id (the model
  returns it with each question); set logs become "set_logs 10, 9, 9".
- Unset values are left out rather than written as a dash or null: a "-"
  for effort_flag was read as a rating ("too easy") in testing.
- The question history becomes topic threads (history_threads): the model
  still sees every topic and every answer it needs and decides what to ask.
"""
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

# Not useful to the model (ids it never refers to); the logs still carry them.
SKIP_KEYS = {"session_id", "plan_id", "user_id"}
# Rendered in their own sections below, in this order.
TOP_KEYS = ("client_name", "gender", "plan_type", "day_number", "is_period", "workout_type")
SECTION_KEYS = {
    "joint_pain", "user_profile", "client_voice_feedback", "client_feedback_notes", "exercises",
    "previous_session", "cardio", "previous_questions_and_answers",
}
EXERCISE_FIELDS = (
    ("movement_type", "movement"), ("unit", "unit"), ("prescribed_sets", "prescribed_sets"),
    ("prescribed_reps", "prescribed_reps"), ("rep_range", "rep_range"), ("set_logs", "set_logs"),
    ("effort_flag", "effort_flag"), ("is_new", "is_new"), ("compared_to_last_time", "compared_to_last_time"),
    ("felt_easier_than_last_time", "felt_easier_than_last_time"), ("progressed_from", "progressed_from"),
    ("loaded_joints", "loaded_joints"),
)
# How many earlier answers a thread keeps besides its latest one: every
# distinct one for a joint (pain) thread, since that's what a follow-up needs.
EARLIER_ANSWERS_PER_THREAD = 1


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _value(value: Any) -> str:
    """A value as plain text: lists joined with commas, dicts as
    "key: value; ...", booleans as yes/no, unset values left out."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, list):
        return ", ".join(_value(item) for item in value if not _empty(item))
    if isinstance(value, dict):
        return "; ".join(f"{key}: {_value(item)}" for key, item in value.items() if not _empty(item))
    return str(value)


def _set_logs(exercise: Dict[str, Any]) -> List[Any]:
    return [log.get("completed_reps") for log in exercise.get("set_logs") or [] if isinstance(log, dict)]


def _exercise_line(exercise: Any) -> List[str]:
    if not isinstance(exercise, dict):
        return [f"- {_value(exercise)}"]
    parts = [f"session_exercise_id {exercise.get('session_exercise_id')}: {exercise.get('name')}"]
    for key, label in EXERCISE_FIELDS:
        value = _set_logs(exercise) if key == "set_logs" else exercise.get(key)
        if not _empty(value):
            parts.append(f"{label} {_value(value)}")
    lines = ["- " + " | ".join(parts)]
    if exercise.get("client_voice_note"):
        lines.append(f"  client_voice_note: {exercise['client_voice_note']}")
    return lines


def _previous_line(exercise: Dict[str, Any]) -> str:
    parts = [str(exercise.get("name"))]
    for key in ("prescribed_reps", "set_logs", "effort_flag"):
        value = _set_logs(exercise) if key == "set_logs" else exercise.get(key)
        if not _empty(value):
            parts.append(f"{key} {_value(value)}")
    return "- " + " | ".join(parts)


def history_threads(history: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """previous_questions_and_answers (one entry per session, newest first;
    repository._shape_question_history) -> one thread per topic: an
    exercise, a joint, or a general question (kept apart per workout type),
    newest first.

    Each thread keeps the latest question's English intent (not its Tamil
    wording, which says the same at about three times the tokens), when it
    was last asked, how many times, the latest real answer ("never
    answered" if none, flagged when the newest ask went unanswered) and
    earlier distinct answers: all of them for a joint thread, one otherwise.
    Nothing is filtered and no answer is judged."""
    threads: Dict[tuple, Dict[str, Any]] = {}
    for session in history:
        # A session lists its round-1 questions before the follow-ups asked
        # after them; read them newest first like the sessions.
        for question in reversed(session.get("questions") or []):
            exercise, joint = question.get("exercise"), question.get("joint")
            general = not exercise and not joint
            key = ("general", session.get("workout_type"), (question.get("intent") or "")[:40]) if general \
                else (exercise, joint)
            answer = question.get("answer")
            thread = threads.get(key)
            if thread is None:
                thread = threads[key] = {
                    "exercise": exercise, "joint": joint,
                    "workout_type": session.get("workout_type") if general else None,
                    "last_asked": session.get("date"), "asked": question.get("intent"),
                    "newest_ask_unanswered": not answer,
                    "last_answer": None, "last_answer_date": None, "times_asked": 0, "earlier_answers": [],
                }
            thread["times_asked"] += 1
            if not answer:
                continue
            if thread["last_answer"] is None:
                thread["last_answer"], thread["last_answer_date"] = answer, session.get("date")
            elif answer != thread["last_answer"] and \
                    answer not in [earlier["answer"] for earlier in thread["earlier_answers"]] and \
                    (joint or len(thread["earlier_answers"]) < EARLIER_ANSWERS_PER_THREAD):
                thread["earlier_answers"].append({"date": session.get("date"), "answer": answer})
    for thread in threads.values():
        if thread["last_answer"] is None:
            thread["last_answer"] = "never answered"
    return list(threads.values())


def _thread_line(thread: Dict[str, Any]) -> str:
    about = " / ".join(str(part) for part in (thread.get("exercise"), thread.get("joint"), thread.get("workout_type"))
                       if part) or "general"
    line = (f"- [{about}] asked {thread['times_asked']}x, last {thread.get('last_asked')}: "
            f"{thread.get('asked')} -> answer: {thread['last_answer']}")
    if thread.get("newest_ask_unanswered") and thread["last_answer"] != "never answered":
        line += " (newest ask unanswered)"
    for earlier in thread.get("earlier_answers") or []:
        line += f" | earlier ({earlier['date']}): {earlier['answer']}"
    return line


def exercise_lines(exercises: Iterable[Any]) -> List[str]:
    """One line per exercise (plus its voice note), led by its session_exercise_id."""
    lines: List[str] = []
    for exercise in exercises:
        lines += _exercise_line(exercise)
    return lines


def history_lines(history: Iterable[Dict[str, Any]]) -> List[str]:
    """previous_questions_and_answers as one line per topic thread."""
    return [_thread_line(thread) for thread in history_threads(history)]


def render_context(context: Dict[str, Any]) -> str:
    """The summary prompt's user message for one session."""
    lines: List[str] = []
    for key in TOP_KEYS:
        if not _empty(context.get(key)):
            lines.append(f"{key}: {_value(context[key])}")
    for key, value in context.items():
        if key not in SKIP_KEYS and key not in TOP_KEYS and key not in SECTION_KEYS and not _empty(value):
            lines.append(f"{key}: {_value(value)}")
    pain = context.get("joint_pain")
    if pain:
        lines.append("joint_pain: " + ", ".join(
            f"{item.get('joint')} ({item.get('pain_level')})" if isinstance(item, dict) else _value(item)
            for item in pain))

    profile = context.get("user_profile")
    if isinstance(profile, dict) and profile:
        lines += ["", "user_profile:"]
        lines += [f"- {key}: {_value(value)}" for key, value in profile.items()
                  if key != "user_id" and not _empty(value) and _value(value)]
    if context.get("client_voice_feedback"):
        lines += ["", f"client_voice_feedback: {context['client_voice_feedback']}"]
    if context.get("client_feedback_notes"):
        lines.append("client_feedback_notes:")
        lines += [f"- {_value(note)}" for note in context["client_feedback_notes"]]

    if context.get("exercises"):
        lines += ["", "exercises:"] + exercise_lines(context["exercises"])
    previous: Optional[Dict[str, Any]] = context.get("previous_session")
    if isinstance(previous, dict):
        if previous.get("exercises"):
            lines += ["", "previous_session (same day last time):"]
            lines += [_previous_line(exercise) for exercise in previous["exercises"] if isinstance(exercise, dict)]
        if previous.get("cardio_rating"):
            lines.append(f"previous_session cardio_rating: {previous['cardio_rating']}")
    if isinstance(context.get("cardio"), dict):
        lines += ["", "cardio:"]
        lines += [f"- {key}: {_value(value)}" for key, value in context["cardio"].items() if not _empty(value)]

    history = context.get("previous_questions_and_answers")
    if history:
        lines += ["", "previous_questions_and_answers (one line per topic, newest first):"]
        lines += history_lines(history)
    return "\n".join(lines).strip()
