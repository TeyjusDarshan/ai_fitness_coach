"""Builds what the AI Coach agent reads for one scheduled session — plain
text, not JSON — and the `facts` its suggestions are validated against
(current prescriptions, rep bounds, allowed swap targets, and the text of
each input section, which every quoted piece of evidence must come from).

The input, in sections (the names are the evidence `source` values):
- `workout`: the upcoming workout, this week's coach notes, the plan's
  safety summary, the joint pain on file now, and every exercise to review
  with its targets, limits, loaded joints, `avoid_if` and the only
  exercises it may be swapped to.
- `summary`: the client's latest stored summary (backend/client_summary),
  which carries her history. Required: missing, or ending before the 7-day
  window starts → SummaryNeededError, and the coach is asked to summarize
  her first.
- `last_7_days`: every workout (strength and cardio) finished or missed in
  the 7 days before the click, the questions asked and answers received in
  them (English intent and answer summary only) and period days.
- `same_day_history`: this workout's training day in the previous two weeks,
  per set, even when older than 7 days — the per-exercise trend.
"""
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any, Dict, List, Optional, Tuple

from agents.prompts_v1 import DAY_TEMPLATES
from backend.client_summary import render
from backend.client_summary.render import parse_reps  # noqa: F401 (re-exported)
from backend.client_summary.repository import ClientSummaryRepository
from backend.client_summary.service import app_timezone
from backend.coach_agent.repository import CoachAgentRepository

RECENT_DAYS = 7
SOURCES = ("workout", "summary", "last_7_days", "same_day_history")


class SummaryNeededError(Exception):
    """The client has no summary, or it ends before the 7-day window."""

    def __init__(self, message: str, covers_until: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.covers_until = covers_until


def _loaded_joints(exercise: Dict[str, Any]) -> List[Tuple[str, str]]:
    """(joint, load) pairs the exercise actually loads (nil left out)."""
    return [
        (link["joints"]["name"], link.get("joint_load"))
        for link in exercise.get("exercise_loaded_joints") or []
        if link.get("joints") and link.get("joint_load") != "nil"
    ]


def _option(exercise: Dict[str, Any], reason: Optional[str]) -> Dict[str, Any]:
    return {
        "exercise_id": exercise["id"],
        "name": exercise["name"],
        "unit": "seconds" if exercise.get("is_time_based") else "reps",
        "min": exercise.get("min_reps"),
        "max": exercise.get("max_reps"),
        "loaded_joints": _loaded_joints(exercise),
        "avoid_if": exercise.get("avoid_if") or None,
        "edge_reason": reason or None,
    }


def _limits(unit: str, low: Any, high: Any) -> str:
    if low is None and high is None:
        return unit
    return f"{unit}, allowed {low if low is not None else '?'}-{high if high is not None else '?'} per set"


def _joints_text(joints: List[Tuple[str, str]]) -> Optional[str]:
    return "loads " + ", ".join(f"{joint} {load}" for joint, load in joints) if joints else None


def _option_line(kind: str, option: Dict[str, Any]) -> str:
    parts = [
        f"  {kind}: [exercise_id {option['exercise_id']}] {option['name']}",
        _limits(option["unit"], option["min"], option["max"]),
        _joints_text(option["loaded_joints"]),
        f"avoid if: {option['avoid_if']}" if option.get("avoid_if") else None,
        f"when: {option['edge_reason']}" if option.get("edge_reason") else None,
    ]
    return " · ".join(p for p in parts if p)


def _safety_text(summary: Any) -> Optional[str]:
    if not isinstance(summary, dict):
        return None
    parts = [
        f"{key.replace('_', ' ')}: {', '.join(str(v) for v in values)}"
        for key, values in summary.items() if values
    ]
    return "; ".join(parts) or None


def _history_block(label: str, session: Dict[str, Any], timezone: str) -> List[str]:
    """One earlier same-day session, per set, in the summary's line format."""
    completed = render.parse_ts(session.get("completed_at"))
    shown = render.local_date(completed, timezone).isoformat() if completed else session.get("scheduled_date")
    status = "completed" if completed else "missed"
    header = f"{label}: {shown} · {status}" + (" · on her period" if session.get("is_period") else "")
    rows = sorted(session.get("session_exercises") or [], key=lambda row: row["id"])
    lines = [header]
    if completed or any(row.get("session_exercise_set_logs") for row in rows):
        for row in rows:
            exercise = row.get("exercises") or {}
            rpe = (row.get("session_exercise_rpe") or {}).get("rpe")
            lines.append(render.exercise_line({
                "name": exercise.get("name"),
                "is_time_based": exercise.get("is_time_based"),
                "sets": row.get("sets"),
                "reps": row.get("reps"),
                "set_logs": sorted(row.get("session_exercise_set_logs") or [], key=lambda log: log["set_number"]),
                "rpe": rpe,
                "rpe_logged": rpe is not None,
                "skipped": row.get("skipped"),
            }))
    return lines


def build_context(
    repo: CoachAgentRepository,
    summary_repo: ClientSummaryRepository,
    plan_repo: Any,
    session: Dict[str, Any],
    now: Optional[datetime] = None,
) -> Tuple[str, Dict[str, Any]]:
    """(plain-text input, facts for validation) for a session row from
    CoachAgentRepository.get_session. Raises SummaryNeededError when the
    client's summary is missing or older than the 7-day window."""
    now = now or datetime.now(dt_timezone.utc)
    tz = app_timezone()
    since = now - timedelta(days=RECENT_DAYS)
    plan = session.get("plans") or {}
    user_id = plan["user_id"]

    latest = summary_repo.get_latest(user_id)
    if latest is None:
        raise SummaryNeededError("This client has no summary yet. Summarize the client first.")
    covers_until = render.parse_ts(latest["covers_until"])
    if covers_until < since:
        raise SummaryNeededError(
            f"The client summary only goes up to {render.local_date(covers_until, tz).isoformat()}, "
            f"more than {RECENT_DAYS} days ago. Summarize the client first.",
            latest["covers_until"],
        )
    summary_text = summary_repo.read_text(latest["storage_path"]).strip()

    # ---------- the workout under review ----------
    rows = sorted(
        session.get("session_exercises") or [],
        key=lambda row: (row.get("category") != "primary", row["id"]),
    )
    edges = repo.get_exercise_edges([row["exercise_id"] for row in rows])
    options: Dict[int, Dict[str, List[Dict[str, Any]]]] = {}
    for edge in edges:
        target = edge.get("exercises")
        if not target:
            continue
        options.setdefault(edge["from_exercise_id"], {"progression": [], "regression": []})
        options[edge["from_exercise_id"]].setdefault(edge["type"], []).append(_option(target, edge.get("reason")))

    split_names = {
        day["day_number"]: day["split_name"]
        for day in DAY_TEMPLATES.get(plan.get("plan_type"), {}).get("schedule", [])
    }
    joint_pain = summary_repo.get_joint_pain(user_id)
    workout = [
        "UPCOMING WORKOUT: " + " · ".join(p for p in (
            session.get("scheduled_date"), f"Day {session['day_number']}", split_names.get(session["day_number"]),
        ) if p),
    ]
    if plan.get("coach_notes"):
        workout.append(f"Coach notes this week: {plan['coach_notes']}")
    safety = _safety_text(plan.get("safety_summary"))
    if safety:
        workout.append(f"Plan safety limits: {safety}")
    workout.append("Joint pain on file now: " + (
        "; ".join(f"{row['joint']} {row['pain_level']}" for row in sorted(joint_pain, key=lambda r: r["joint"]))
        or "none"
    ))
    workout.append("")
    workout.append("EXERCISES TO REVIEW")

    facts_by_id = {}
    for row in rows:
        exercise = row.get("exercises") or {}
        reps = parse_reps(row.get("reps"), row.get("sets"))
        locked = bool(row.get("session_exercise_set_logs"))
        skipped = bool(row.get("skipped"))
        unit = "seconds" if exercise.get("is_time_based") else "reps"
        own_options = options.get(row["exercise_id"], {"progression": [], "regression": []})
        status = "skipped (no suggestion)" if skipped else "locked, sets logged (no suggestion)" if locked else "open"
        prescribed = (
            f"prescribed {row.get('sets')} sets: {', '.join(str(r) for r in reps)} {'s' if unit == 'seconds' else 'reps'}"
            if reps else None
        )
        workout.append(" · ".join(p for p in (
            f"[session_exercise_id {row['id']}] {exercise.get('name')}",
            status,
            _limits(unit, exercise.get("min_reps"), exercise.get("max_reps")),
            prescribed,
            _joints_text(_loaded_joints(exercise)),
            f"avoid if: {exercise['avoid_if']}" if exercise.get("avoid_if") else None,
            f"coach note: {row['note']}" if row.get("note") else None,
        ) if p))
        if not locked and not skipped:
            for kind in ("progression", "regression"):
                workout += [_option_line(kind, option) for option in own_options.get(kind, [])]
        facts_by_id[row["id"]] = {
            "session_exercise_id": row["id"],
            "exercise_id": row["exercise_id"],
            "name": exercise.get("name"),
            "is_time_based": bool(exercise.get("is_time_based")),
            "sets": row.get("sets"),
            "reps": reps,
            "reps_stored": row.get("reps"),
            "min": exercise.get("min_reps"),
            "max": exercise.get("max_reps"),
            "actionable": not locked and not skipped,
            "options": {
                direction: {option["exercise_id"]: option for option in own_options.get(direction, [])}
                for direction in ("progression", "regression")
            },
        }

    # ---------- the last 7 days ----------
    plans = summary_repo.get_plans(user_id)
    plans_by_id = {p["id"]: p for p in plans}
    weeks = {p["id"]: index + 1 for index, p in enumerate(plans)}
    past = plan_repo.get_user_workout_history(user_id)["past"] if plans else []
    workouts = render.workout_lines(past, plans_by_id, weeks, since, now, tz)
    rounds = summary_repo.get_question_rounds(user_id)
    names = summary_repo.get_exercise_names([
        q["session_exercise_id"] for r in rounds for q in r.get("questions") or [] if q.get("session_exercise_id")
    ])
    qa = render.qa_lines(rounds, names, since, now, tz)
    period = render.period_lines(summary_repo.get_period_logs(user_id, since, now))
    recent = ["WORKOUTS (oldest first)"] + (workouts or ["none"])
    recent += ["", "QUESTIONS WE ASKED AND HER ANSWERS"] + (qa or ["none"])
    recent += ["", "PERIOD"] + (period or ["none"])

    # ---------- same training day, previous two weeks ----------
    history = repo.get_same_day_history(plan.get("parent_plan_id"), session["day_number"])
    same_day: List[str] = []
    for weeks_ago, earlier in enumerate(history, start=1):
        same_day += _history_block(f"{weeks_ago} week{'s' if weeks_ago > 1 else ''} before", earlier, tz)
    if not same_day:
        same_day = ["none (first weeks of her plan)"]

    sections = {
        "workout": "\n".join(workout),
        "summary": summary_text,
        "last_7_days": "\n".join(recent),
        "same_day_history": "\n".join(same_day),
    }
    window = f"{render.local_date(since, tz).isoformat()} to {render.local_date(now, tz).isoformat()}"
    text = "\n\n".join([
        f"TODAY: {render.local_date(now, tz).isoformat()}",
        "===== [workout] THE WORKOUT TO REVIEW =====\n" + sections["workout"],
        f"===== [summary] CLIENT SUMMARY (her history up to "
        f"{covers_until.astimezone(render._tz(tz)).strftime('%Y-%m-%d %H:%M')}) =====\n" + sections["summary"],
        f"===== [last_7_days] THE LAST {RECENT_DAYS} DAYS ({window}) =====\n" + sections["last_7_days"],
        "===== [same_day_history] THIS TRAINING DAY IN THE PREVIOUS TWO WEEKS =====\n" + sections["same_day_history"],
    ]) + "\n"
    facts = {"user_id": user_id, "exercises": facts_by_id, "sections": sections, "summary_version": latest["version"]}
    return text, facts
