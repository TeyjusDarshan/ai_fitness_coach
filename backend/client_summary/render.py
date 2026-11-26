"""The client summary's user message, as plain text (no JSON).

Pure functions over rows the repository has already read. Two kinds of
input:

- **Current state**, always sent whole: her profile and the joint pain on
  file. Both are overwritten in place (no history), so a change between two
  runs would otherwise be missed. `state_hash` fingerprints it, so a click
  with no new events and the same state can skip the Claude call.
- **Events**, cut by time: workouts finished or missed, questions asked and
  answers received, coach notes taken from her voice notes and replies
  (`workout_comments`), and period days. Only the ones in the window
  (after the previous summary's cut-off, up to this run's) are sent.

English only: a question's `intent` and the answer's English `summary`,
never the Tamil question text or her reply transcript; a comment's English
`comment`, never her `quote`. Unset values are left out, never written as a
dash (a dash was misread as a rating in the summary experiment).
"""
import hashlib
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo


RPE_FELT = {6: "felt too easy", 8: "felt about right", 10: "felt too hard"}
CARDIO_RATING = {"easy": "rated it easy", "medium": "rated it about right", "hard": "rated it too difficult"}
COMMENT_SOURCE = {
    "session_voice_note": "workout voice note",
    "exercise_voice_note": "exercise voice note",
    "clarification_reply": "WhatsApp reply",
}
# A cardio exercise done for less than this share of its time "stopped early"
# (the same threshold the analysis consumer uses).
STOPPED_EARLY_SHARE = 0.8
# Profile keys that say nothing about her (ids) or are shown elsewhere.
PROFILE_SKIP_KEYS = {"user_id"}


def parse_reps(reps: Any, sets: Optional[int]) -> List[int]:
    """A stored `reps` ("12", or per set "12,10,10") as one target per set."""
    sets = sets or 0
    parts = [int(part) for part in str(reps or "").split(",") if part.strip().isdigit()]
    if not parts:
        return []
    if len(parts) == 1:
        return parts * sets if sets else parts
    return parts


def _tz(timezone: str) -> ZoneInfo:
    return ZoneInfo(timezone)


def parse_ts(value: Optional[str]) -> Optional[datetime]:
    """A timestamptz from PostgREST (any fraction length, 'Z' or offset)."""
    if not value:
        return None
    text = value.replace("Z", "+00:00").replace(" ", "T", 1)
    # Python < 3.11 wants exactly 3 or 6 fraction digits.
    if "." in text:
        head, rest = text.split(".", 1)
        digits = rest[: len(rest) - len(rest.lstrip("0123456789"))]
        tail = rest[len(digits):]
        text = f"{head}.{(digits + '000000')[:6]}{tail}"
    return datetime.fromisoformat(text)


def in_window(moment: Optional[datetime], since: Optional[datetime], until: datetime) -> bool:
    """(since, until]: after the previous cut-off, up to this run's."""
    if moment is None:
        return False
    return (since is None or moment > since) and moment <= until


def local_date(moment: datetime, timezone: str) -> date:
    return moment.astimezone(_tz(timezone)).date()


def _day(d: date) -> str:
    return f"{d.isoformat()} ({d.strftime('%a')})"


def _humanize(value: Any) -> str:
    return str(value).replace("_", " ")


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


# ---------- current state ----------

def _profile_value(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, dict):
        parts = [f"{_humanize(k)} {_profile_value(v)}" for k, v in value.items() if not _empty(v)]
        return ", ".join(parts)
    if isinstance(value, list):
        return "; ".join(_profile_value(item) for item in value if not _empty(item))
    return _humanize(value) if isinstance(value, str) and "_" in value and " " not in value else str(value)


def profile_lines(profile: Optional[Dict[str, Any]]) -> List[str]:
    """The generated profile as `section.key: value` lines, unset ones left out."""
    lines = []
    for section, body in (profile or {}).items():
        if section in PROFILE_SKIP_KEYS or _empty(body):
            continue
        if not isinstance(body, dict):
            lines.append(f"{_humanize(section)}: {_profile_value(body)}")
            continue
        for key, value in body.items():
            if _empty(value):
                continue
            lines.append(f"{_humanize(section)}.{_humanize(key)}: {_profile_value(value)}")
    return lines


def state_text(profile_row: Dict[str, Any], joint_pain: List[Dict[str, Any]], timezone: str) -> str:
    lines = ["CLIENT (current profile)"]
    if profile_row.get("name"):
        lines.append(f"name: {profile_row['name']}")
    if profile_row.get("gender"):
        lines.append(f"gender: {profile_row['gender']}")
    lines += profile_lines(profile_row.get("profile"))
    lines += ["", "JOINT PAIN ON FILE NOW"]
    if not joint_pain:
        lines.append("none")
    for row in sorted(joint_pain, key=lambda r: r["joint"]):
        updated = parse_ts(row.get("updated_at"))
        since = f" (last changed {local_date(updated, timezone).isoformat()})" if updated else ""
        lines.append(f"- {row['joint']}: {row['pain_level']}{since}")
    return "\n".join(lines)


def state_hash(profile_row: Dict[str, Any], joint_pain: List[Dict[str, Any]]) -> str:
    """Fingerprint of what the state says (not when it was last touched: an
    upsert bumps updated_at even when the level is the same)."""
    pain = sorted((row["joint"], row["pain_level"]) for row in joint_pain)
    basis = repr((profile_row.get("name"), profile_row.get("gender"), profile_lines(profile_row.get("profile")), pain))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


# ---------- workouts ----------

def workout_event_time(workout: Dict[str, Any], plan: Dict[str, Any], timezone: str) -> Optional[datetime]:
    """When a past workout became part of her history: its completion, or for
    a missed one the moment it was missed — the start of the day after its
    scheduled date, or the plan's close if the coach closed it earlier."""
    if workout.get("completed_at"):
        return parse_ts(workout["completed_at"])
    next_day = date.fromisoformat(workout["scheduled_date"]) + timedelta(days=1)
    missed_at = datetime.combine(next_day, time.min, tzinfo=_tz(timezone))
    closed_at = parse_ts(plan.get("completed_at"))
    return min(missed_at, closed_at) if closed_at else missed_at


def _reps_text(values: List[int], unit: str) -> str:
    if values and len(set(values)) == 1:
        return f"{len(values)} x {values[0]} {unit}"
    return f"{', '.join(str(v) for v in values)} {unit}"


def exercise_line(exercise: Dict[str, Any]) -> str:
    name = exercise["name"]
    if exercise.get("skipped"):
        reason = f" ({exercise['skip_reason']})" if exercise.get("skip_reason") else ""
        return f"- {name}: skipped by the coach for this workout{reason}"
    unit = "s" if exercise.get("is_time_based") else "reps"
    planned = parse_reps(exercise.get("reps"), exercise.get("sets"))
    parts = [f"planned {_reps_text(planned, unit)}" if planned else None]
    done = [log["completed_reps"] for log in exercise.get("set_logs") or []]
    if done:
        missing = max(0, (exercise.get("sets") or 0) - len(done))
        parts.append(f"done {', '.join(str(v) for v in done)}" + (f" ({missing} set(s) not done)" if missing else ""))
    else:
        parts.append("no sets done")
    if exercise.get("rpe_logged"):
        parts.append(RPE_FELT.get(exercise.get("rpe"), f"effort {exercise.get('rpe')}/10"))
    elif done:
        parts.append("effort not rated")
    return f"- {name}: " + "; ".join(p for p in parts if p)


def cardio_line(cardio: Dict[str, Any]) -> str:
    rounds, seconds = cardio.get("rounds"), cardio.get("work_seconds")
    level = f"{rounds} round(s) x {seconds} s per exercise"
    planned = cardio.get("planned_work_seconds")
    if planned and planned != seconds:
        level += f" (level {planned} s, shortened for her period)"
    parts = [f"- Cardio circuit: {level}"]
    rating = cardio.get("rating")
    parts.append(CARDIO_RATING.get(rating, "not rated"))
    summary = cardio.get("log_summary") or {}
    log = cardio.get("log") or []
    if log:
        parts.append(f"{summary.get('exercises_done', 0)} exercise(s) done")
        skipped = [
            f"{e['name']} ({e['actual_seconds']} s in)" if e.get("actual_seconds") else e["name"]
            for e in log if e.get("skipped")
        ]
        if skipped:
            parts.append("skipped " + ", ".join(skipped))
        early = [
            f"{e['name']} ({e['actual_seconds']} of {e['planned_seconds']} s)"
            for e in log
            if not e.get("skipped") and e.get("actual_seconds") is not None and e.get("planned_seconds")
            and e["actual_seconds"] < STOPPED_EARLY_SHARE * e["planned_seconds"]
        ]
        if early:
            parts.append("stopped early: " + ", ".join(early))
        if summary.get("exercises_missing"):
            parts.append(f"{summary['exercises_missing']} exercise(s) never reached")
        if summary.get("rests_skipped"):
            parts.append(f"{summary['rests_skipped']} rest(s) skipped")
    return "; ".join(parts)


def workout_block(workout: Dict[str, Any], week: Optional[int], timezone: str) -> List[str]:
    shown = date.fromisoformat(workout["date"])
    label = " · ".join(p for p in (
        _day(shown),
        f"Week {week}, Day {workout['day_number']}" if week else f"Day {workout['day_number']}",
        workout.get("name"),
    ) if p)
    status = workout["status"]
    if status == "completed":
        minutes = round((workout.get("duration_seconds") or 0) / 60)
        status = f"completed in {minutes} min" if minutes else "completed"
    elif workout.get("started_at"):
        status = "missed (started but not finished)"
    header = f"{label} · {status}" + (" · on her period" if workout.get("is_period") else "")
    lines = [header]
    if workout.get("kind") == "cardio":
        if workout["status"] == "completed" or (workout.get("cardio") or {}).get("log"):
            lines.append(cardio_line(workout.get("cardio") or {}))
        return lines
    exercises = workout.get("exercises") or []
    if workout["status"] == "completed" or any(e.get("set_logs") for e in exercises):
        lines += [exercise_line(e) for e in exercises]
    return lines


def workout_lines(
    workouts: Iterable[Dict[str, Any]],
    plans: Dict[int, Dict[str, Any]],
    weeks: Dict[int, int],
    since: Optional[datetime],
    until: datetime,
    timezone: str,
) -> List[str]:
    """Past workouts (completed or missed) that entered her history in the
    window, oldest first."""
    chosen: List[Tuple[datetime, Dict[str, Any]]] = []
    for workout in workouts:
        if workout.get("status") not in ("completed", "missed"):
            continue
        moment = workout_event_time(workout, plans.get(workout["plan_id"]) or {}, timezone)
        if in_window(moment, since, until):
            chosen.append((moment, workout))
    lines: List[str] = []
    for _, workout in sorted(chosen, key=lambda pair: pair[0]):
        lines += workout_block(workout, weeks.get(workout["plan_id"]), timezone)
    if chosen:
        lines.insert(0, count_line([workout for _, workout in chosen]))
    return lines


def count_line(workouts: List[Dict[str, Any]]) -> str:
    """Counted by code: the model miscounted sessions when left to it."""
    def counts(kind: str) -> str:
        of_kind = [w for w in workouts if (w.get("kind") or "strength") == kind]
        done = sum(1 for w in of_kind if w["status"] == "completed")
        return f"{kind} {done} completed, {len(of_kind) - done} missed"
    period = sum(1 for w in workouts if w.get("is_period") and w["status"] == "completed")
    first = min(w["date"] for w in workouts)
    last = max(w["date"] for w in workouts)
    return (
        f"Counts ({first} to {last}): {len(workouts)} workouts; {counts('strength')}; {counts('cardio')}"
        + (f"; {period} done on her period" if period else "")
    )


# ---------- questions and answers ----------

def qa_lines(
    rounds: Iterable[Dict[str, Any]],
    exercise_names: Dict[int, str],
    since: Optional[datetime],
    until: datetime,
    timezone: str,
) -> List[str]:
    """Questions asked in the window (with their answer if one arrived by the
    cut-off), then answers that arrived in the window to questions asked
    before it. English intent and answer summary only."""
    asked_now: Dict[int, Dict[str, Any]] = {}
    late_answers: List[Tuple[datetime, str]] = []
    for row in sorted(rounds, key=lambda r: (r.get("asked_at") or "", r.get("round") or 1)):
        asked_at = parse_ts(row.get("asked_at"))
        reply_times = {
            reply["id"]: parse_ts(reply.get("created_at")) for reply in row.get("clarification_replies") or []
        }
        session = row.get("sessions") or {}
        workout_day = (session.get("completed_at") or "")[:10] or session.get("scheduled_date")
        answers = row.get("answers") or {}
        asked_in_window = in_window(asked_at, since, until)
        for question in row.get("questions") or []:
            intent = question.get("intent") or "(no intent recorded)"
            about = [exercise_names.get(question.get("session_exercise_id")), question.get("joint")]
            about_text = " / ".join(a for a in about if a)
            subject = f"About {about_text}: " if about_text else ""
            follow_up = "[follow-up] " if (row.get("round") or 1) > 1 else ""
            answer = answers.get(question.get("id")) or {}
            answered_at = reply_times.get(answer.get("reply_id")) or (asked_at if answer.get("summary") else None)
            answer_known = bool(answer.get("summary")) and answered_at is not None and answered_at <= until
            if asked_in_window:
                if answer_known:
                    outcome = f"Answer: {answer['summary']}"
                elif row.get("status") in ("expired", "superseded", "answered"):
                    outcome = "Not answered."
                else:
                    outcome = "No answer yet."
                group = asked_now.setdefault(row["session_id"], {"day": workout_day, "kind": session.get("kind"), "lines": []})
                group["lines"].append(f"- {follow_up}{subject}{intent} -> {outcome}")
            elif answer_known and in_window(answered_at, since, until):
                late_answers.append((answered_at, (
                    f"- Answer received {local_date(answered_at, timezone).isoformat()} to a question asked "
                    f"after the {workout_day} workout. {subject}{intent} -> Answer: {answer['summary']}"
                )))
    lines: List[str] = []
    for group in asked_now.values():
        kind = f" {group['kind']}" if group.get("kind") else ""
        lines.append(f"After the {group['day']}{kind} workout:")
        lines += group["lines"]
    lines += [line for _, line in sorted(late_answers, key=lambda pair: pair[0])]
    return lines


# ---------- comments and period ----------

def comment_lines(comments: Iterable[Dict[str, Any]], timezone: str) -> List[str]:
    """Coach notes taken from her voice notes and replies: the English
    `comment` only, never her own words (`quote`)."""
    lines = []
    for row in sorted(comments, key=lambda r: r.get("created_at") or ""):
        if not row.get("comment"):
            continue
        created = parse_ts(row.get("created_at"))
        where = [
            local_date(created, timezone).isoformat() if created else None,
            (row.get("exercises") or {}).get("name"),
            COMMENT_SOURCE.get(row.get("source")),
        ]
        urgent = " [URGENT]" if row.get("urgent") else ""
        lines.append(f"- {' · '.join(w for w in where if w)}: {row['comment']}{urgent}")
    return lines


def period_lines(rows: Iterable[Dict[str, Any]]) -> List[str]:
    days = sorted({row["logged_on"] for row in rows if row.get("logged_on")})
    return [f"Period days logged: {', '.join(days)}"] if days else []


# ---------- the whole message ----------

def render_input(
    *,
    today: date,
    state: str,
    previous_summary: Optional[str],
    since: Optional[datetime],
    until: datetime,
    timezone: str,
    workouts: List[str],
    qa: List[str],
    comments: List[str],
    period: List[str],
) -> str:
    def section(title: str, lines: List[str]) -> List[str]:
        return ["", title] + (lines or ["none"])

    if previous_summary is not None and since is not None:
        cutoff = since.astimezone(_tz(timezone)).strftime("%Y-%m-%d %H:%M")
        mode = f"UPDATE: the previous summary covers everything up to {cutoff}. Below is only what arrived after that."
        events_title = f"NEW SINCE {cutoff}"
    else:
        mode = "FIRST SUMMARY: below is her whole history."
        events_title = "HER HISTORY"
    lines = [f"TODAY: {_day(today)}", mode, "", state]
    if previous_summary is not None:
        lines += ["", "PREVIOUS SUMMARY", previous_summary.strip()]
    lines += ["", f"===== {events_title} ====="]
    lines += section("WORKOUTS (oldest first)", workouts)
    lines += section("QUESTIONS WE ASKED AND HER ANSWERS", qa)
    lines += section("COACH NOTES FROM HER VOICE NOTES AND REPLIES", comments)
    lines += section("PERIOD", period)
    return "\n".join(lines).strip() + "\n"
