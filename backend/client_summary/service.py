"""Builds or updates one client's summary (the admin "Summarize client"
button).

- First run, or `rebuild`: her whole history, no previous summary.
- Later runs: the latest version's TXT plus only what arrived after its
  cut-off (`covers_until`), plus her current profile and joint pain.
- Nothing new and the same state → no Claude call; the latest version is
  returned with `nothing_new`.

The cut-off is the run's start time, and every read is bounded by it, so
something written while the run is in progress is picked up next time
rather than counted twice or lost. Only finished or missed workouts are
read, so one in progress is picked up once it ends.
"""
import os
from datetime import datetime, timezone as dt_timezone
from typing import Any, Callable, Dict, Optional

from backend.client_summary import render
from backend.client_summary.repository import ClientSummaryRepository
from backend.repository.workout_plan_repository import WorkoutPlanRepository


class ClientNotFoundError(LookupError):
    pass


def app_timezone() -> str:
    # Workouts (scheduled dates, missed days) run on APP_TIMEZONE, not her own zone.
    return os.environ.get("APP_TIMEZONE", "Asia/Kolkata")


def build_input(
    repo: ClientSummaryRepository,
    plan_repo: WorkoutPlanRepository,
    user_id: str,
    previous: Optional[Dict[str, Any]],
    previous_text: Optional[str],
    until: datetime,
) -> Dict[str, Any]:
    """The user message for this run and what decides whether it's needed."""
    tz = app_timezone()
    profile_row = repo.get_profile_row(user_id)
    if profile_row is None:
        raise ClientNotFoundError(user_id)
    since = render.parse_ts(previous["covers_until"]) if previous else None
    joint_pain = repo.get_joint_pain(user_id)

    plans = repo.get_plans(user_id)
    plans_by_id = {plan["id"]: plan for plan in plans}
    weeks = {plan["id"]: index + 1 for index, plan in enumerate(plans)}
    past = plan_repo.get_user_workout_history(user_id)["past"] if plans else []
    workouts = render.workout_lines(past, plans_by_id, weeks, since, until, tz)

    rounds = repo.get_question_rounds(user_id)
    names = repo.get_exercise_names([
        q["session_exercise_id"] for r in rounds for q in r.get("questions") or [] if q.get("session_exercise_id")
    ])
    qa = render.qa_lines(rounds, names, since, until, tz)
    comments = render.comment_lines(repo.get_comments(user_id, since, until), tz)
    period = render.period_lines(repo.get_period_logs(user_id, since, until))

    state = render.state_text(profile_row, joint_pain, tz)
    message = render.render_input(
        today=render.local_date(until, tz),
        state=state,
        previous_summary=previous_text,
        since=since,
        until=until,
        timezone=tz,
        workouts=workouts,
        qa=qa,
        comments=comments,
        period=period,
    )
    return {
        "message": message,
        "since": since,
        "state_hash": render.state_hash(profile_row, joint_pain),
        "has_events": bool(workouts or qa or comments or period),
    }


def summarize_client(
    repo: ClientSummaryRepository,
    plan_repo: WorkoutPlanRepository,
    user_id: str,
    summarize: Callable[[str, Optional[str]], tuple],
    rebuild: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """{"summary": version row + text, "nothing_new": bool}."""
    until = now or datetime.now(dt_timezone.utc)
    latest = repo.get_latest(user_id)
    previous = None if rebuild else latest
    previous_text = repo.read_text(previous["storage_path"]) if previous else None

    built = build_input(repo, plan_repo, user_id, previous, previous_text, until)
    if previous and not built["has_events"] and built["state_hash"] == previous["state_hash"]:
        return {"summary": {**previous, "text": previous_text}, "nothing_new": True}

    text, model = summarize(built["message"], user_id)
    row = repo.save({
        "user_id": user_id,
        "version": (latest["version"] + 1) if latest else 1,
        "covers_from": built["since"].isoformat() if built["since"] else None,
        "covers_until": until.isoformat(),
        "state_hash": built["state_hash"],
        "word_count": len(text.split()),
        "rebuilt": bool(rebuild and latest),
        "model": model,
    }, text)
    return {"summary": {**row, "text": text}, "nothing_new": False}


def latest_summary(repo: ClientSummaryRepository, user_id: str) -> Optional[Dict[str, Any]]:
    latest = repo.get_latest(user_id)
    if latest is None:
        return None
    return {**latest, "text": repo.read_text(latest["storage_path"])}
