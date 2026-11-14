import logging
import os
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from supabase import create_client, Client

from agents.prompts_v1 import DAY_TEMPLATES
from backend.cardio import (
    CARDIO_DAYS,
    CARDIO_GET_READY_SECONDS,
    CARDIO_RATINGS,
    CARDIO_ROUND_REST_SECONDS,
    CARDIO_SPLIT_NAME,
    CARDIO_START,
    KIND_CARDIO,
    KIND_STRENGTH,
    MEDIUM,
    actual_work_seconds,
    cardio_day,
    estimated_seconds,
    exercise_rest_seconds,
    is_cardio,
    next_level,
    session_level,
    week_outcome,
)
from backend.repository.workout_repository import WorkoutRepository

load_dotenv()

logger = logging.getLogger(__name__)

SESSION_EXERCISE_JOIN = (
    "*, exercises(*, movement_types(name), equipment(name), exercise_loaded_joints(joints(name))), "
    "session_exercise_set_logs(set_number, completed_reps), session_exercise_rpe(rpe)"
)

# A plan's sessions (one per training day) with their exercises nested in.
# (A cardio session's step-by-step record comes along as session_cardio_logs.)
PLAN_SESSIONS_SELECT = f"*, session_exercises({SESSION_EXERCISE_JOIN}), session_cardio_logs(*)"

# Lighter than SESSION_EXERCISE_JOIN: progression only needs exercise_id (not
# the nested exercises(...) join) since it's carried forward as-is into the
# next plan's session_exercises rows, never rendered.
PROGRESSION_EXERCISE_SELECT = (
    "id, exercise_id, category, slot_label, sets, reps, rep_range, note, skipped, "
    "session_exercise_set_logs(set_number, completed_reps), session_exercise_rpe(rpe)"
)
PROGRESSION_SESSIONS_SELECT = (
    f"id, day_number, scheduled_date, completed_at, is_period, "
    f"kind, cardio_rounds, cardio_work_seconds, cardio_rating, "
    f"session_exercises({PROGRESSION_EXERCISE_SELECT})"
)

# Just what cardio progression reads from an earlier plan's sessions.
CARDIO_HISTORY_SELECT = (
    "day_number, completed_at, is_period, kind, cardio_rounds, cardio_work_seconds, cardio_rating"
)

# Public Storage bucket holding the cardio circuit's clips and poster frames.
CARDIO_VIDEO_BUCKET = "cardio-videos"
# A logged cardio step's seconds (done or paused) must fall in 0..this.
CARDIO_LOG_MAX_SECONDS = 600
CARDIO_LOG_PARTS = ("exercise", "rest")

# How long the cardio circuit (cardio_exercises) is cached per repository.
CARDIO_CIRCUIT_TTL_SECONDS = 300

# Each auto-progressed plan's sessions land one week after the same day of
# the plan it was progressed from (or start today, if that's already past —
# see create_progressed_plan).
PROGRESSION_SCHEDULE_OFFSET = timedelta(days=7)

# Autoregulated-progression constants — see _compute_progressed_reps.
PROGRESSION_MIN_REPS = 1

# Easy/Medium/Hard = rpe 6/8/10, matching the frontend's EffortSlider — a
# reported rpe outside {6, 8, 10} is possible via direct API use, so
# _compute_progressed_reps snaps it to whichever of these it's closest to.
RPE_TOO_EASY, RPE_CORRECT, RPE_HARD = 6, 8, 10
_RPE_BUCKETS = (RPE_TOO_EASY, RPE_CORRECT, RPE_HARD)
# No rpe was ever logged: assume correct if every set hit its target, else hard.
PROGRESSION_UNRATED_HIT_RPE = RPE_CORRECT
PROGRESSION_FALLBACK_RPE = RPE_HARD
PROGRESSION_CORRECT_STEP = 1
# Too easy (with every target met): added to EVERY set, on top of the reps
# she actually did (not the prescribed targets).
PROGRESSION_EASY_STEP = 1
PROGRESSION_HARD_STEP = 1
# The same steps for a timed exercise (exercises.is_time_based), in seconds.
TIMED_CORRECT_STEP = 5
TIMED_EASY_STEP = 5
TIMED_HARD_STEP = 5

# A session started during a period runs at this fraction of its planned reps
# (see WorkoutPlanRepository._apply_period_adjustment).
PERIOD_REP_FACTOR = 0.7

# How many plans back (via parent_plan_id) progression will look for a day's
# latest non-period sessions before giving up.
MAX_PROGRESSION_HOPS = 8

# exercise_relationships.reason is semicolon-delimited when an edge has more
# than one reason (e.g. "Lack of form;Lack of strength") — substring match
# catches both that and the plain "Lack of strength" case.
REGRESSION_REASON_FILTER = "lack of strength"


def app_today() -> date:
    """Today's date in the app's timezone (APP_TIMEZONE, default IST), which
    decides when a session's scheduled_date has arrived."""
    return datetime.now(ZoneInfo(os.environ.get("APP_TIMEZONE", "Asia/Kolkata"))).date()


def app_date(timestamp: str) -> date:
    """The calendar date, in the app's timezone, of a timestamptz value
    (e.g. a session's completed_at)."""
    return datetime.fromisoformat(timestamp).astimezone(
        ZoneInfo(os.environ.get("APP_TIMEZONE", "Asia/Kolkata"))
    ).date()


def scheduled_date_for(start_date: date, day_number: int) -> date:
    """Day N of a plan falls N-1 days after the plan's start date."""
    return start_date + timedelta(days=day_number - 1)


def _cardio_media_url(path: Optional[str]) -> Optional[str]:
    """Public URL of an object in the cardio-videos bucket (built locally,
    the same way storage.get_public_url does)."""
    if not path:
        return None
    base = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    return f"{base}/storage/v1/object/public/{CARDIO_VIDEO_BUCKET}/{quote(path)}"


def _cardio_log(session: dict, planned_steps: int) -> Dict[str, Any]:
    """A cardio session's step-by-step record (session_cardio_logs) for its
    `cardio` block: `log`, one entry per exercise per round in order, and
    `log_summary`. An exercise is done when its time was logged and it
    wasn't skipped; `exercises_missing` counts the planned ones never
    logged at all (she left before reaching them)."""
    rows = sorted(session.get("session_cardio_logs") or [], key=lambda r: (r["round"], r["position"]))
    log = [
        {
            "round": r["round"],
            "position": r["position"],
            "name": r["exercise_name"],
            "planned_seconds": r["planned_seconds"],
            "actual_seconds": r.get("actual_seconds"),
            "paused_seconds": r.get("paused_seconds"),
            "skipped": bool(r.get("skipped")),
            "rest_planned_seconds": r.get("rest_planned_seconds"),
            "rest_actual_seconds": r.get("rest_actual_seconds"),
            "rest_paused_seconds": r.get("rest_paused_seconds"),
            "rest_skipped": bool(r.get("rest_skipped")),
        }
        for r in rows
    ]
    logged = [entry for entry in log if entry["actual_seconds"] is not None]
    return {
        "log": log,
        "log_summary": {
            "exercises_done": sum(1 for entry in logged if not entry["skipped"]),
            "exercises_skipped": sum(1 for entry in logged if entry["skipped"]),
            "exercises_missing": max(0, planned_steps - len(logged)),
            "rests_skipped": sum(1 for entry in log if entry["rest_skipped"]),
            "active_seconds": sum(entry["actual_seconds"] or 0 for entry in log),
            "paused_seconds": sum(
                (entry["paused_seconds"] or 0) + (entry["rest_paused_seconds"] or 0) for entry in log
            ),
        },
    }


def is_session_missed(session: dict, today: date) -> bool:
    """A session is missed once its scheduled_date has passed without it being
    completed — including one that was started (sets logged) but never
    finished. Derived, never stored: a missed session can't be started or
    logged any more, and counts as resolved for closing out its plan."""
    return not session.get("completed_at") and date.fromisoformat(session["scheduled_date"]) < today


def workout_status(workout: dict, today: date, plan_closed: bool = False) -> Tuple[str, str]:
    """(status, display date) for a _workout_entries entry: "completed" on its
    completion date (in APP_TIMEZONE), else "missed" (date passed, or its
    plan is already closed — e.g. the coach closed it early) or "scheduled",
    on its scheduled date. Shared by the dashboard and the admin monitor."""
    if workout.get("completed_at"):
        return "completed", app_date(workout["completed_at"]).isoformat()
    status = "missed" if plan_closed or is_session_missed(workout, today) else "scheduled"
    return status, workout["scheduled_date"]


def workout_duration_seconds(workout: dict) -> Optional[int]:
    """Seconds from started_at to completed_at, or None until both are set."""
    if not (workout.get("started_at") and workout.get("completed_at")):
        return None
    return int(
        (datetime.fromisoformat(workout["completed_at"]) - datetime.fromisoformat(workout["started_at"]))
        .total_seconds()
    )


def _flatten_session_exercises(sessions: List[dict]) -> List[dict]:
    """Pull each session's nested session_exercises rows out into one list,
    tagging every row with its session's day_number and whether it was
    missed (its session never completed — by the time a plan is progressed,
    every uncompleted session is a missed one — or the coach skipped the
    exercise that day; either way it carries forward unchanged), ordered by
    day then id."""
    rows = []
    for session in sorted(sessions, key=lambda s: s["day_number"]):
        for row in sorted(session.get("session_exercises") or [], key=lambda r: r["id"]):
            rows.append({
                **row,
                "day_number": session["day_number"],
                "missed": not session.get("completed_at") or bool(row.get("skipped")),
            })
    return rows


# update_session_exercise_prescription's default: leave the note as it is.
_KEEP = object()


def _rep_range(exercise: dict) -> Optional[str]:
    """A library exercise's "min-max" rep range, or None if either is unset."""
    low, high = exercise.get("min_reps"), exercise.get("max_reps")
    return f"{low}-{high}" if low is not None and high is not None else None


class PlanRegenerationError(Exception):
    """Why a client's current week can't be rebuilt (shown to the coach)."""


class CardioLogError(ValueError):
    """Why a cardio step can't be logged against a session (shown to the client)."""


class PainLevel(Enum):
    MILD = "mild"       # 1-3
    MODERATE = "moderate"  # 4-7
    SEVERE = "severe"   # 8-10


# Corrected Joint Load Factors: (pain_level, exercise_loaded_joints.joint_load)
# -> injury multiplier. 0.0 means the exercise should be excluded outright
# for that joint at that pain level, not just down-weighted. "nil" (no load)
# is always 1.0 since the exercise isn't touching that joint at all.
JOINT_LOAD_INJURY_MULTIPLIERS: Dict[PainLevel, Dict[str, float]] = {
    PainLevel.MILD: {"high": 0.4, "mid": 0.7, "low": 1.0, "nil": 1.0},
    PainLevel.MODERATE: {"high": 0.0, "mid": 0.3, "low": 0.6, "nil": 1.0},
    PainLevel.SEVERE: {"high": 0.0, "mid": 0.0, "low": 0.3, "nil": 1.0},
}


def _parse_target_reps(reps: Optional[str], sets: int) -> List[int]:
    """Previous per-set target list from a session_exercises row's `reps`.

    `reps` is either a single number (uniform across all sets — a brand-new
    plan from create_plan, or a fully caught-up ramp) or a
    comma-separated per-set list written by a previous progression while one
    set is ahead of the others (e.g. "11,10,10" — see _bump_next_set).
    """
    if not reps:
        return [PROGRESSION_MIN_REPS] * sets
    values = [int(v) for v in str(reps).split(",")]
    return values if len(values) > 1 else values * sets


def _scale_reps_for_period(target_reps: List[int]) -> List[int]:
    """Each set's target at PERIOD_REP_FACTOR of planned, rounded half up."""
    return [max(PROGRESSION_MIN_REPS, int(r * PERIOD_REP_FACTOR + 0.5)) for r in target_reps]


def _nearest_rpe_bucket(rpe: int) -> int:
    return min(_RPE_BUCKETS, key=lambda bucket: abs(bucket - rpe))


def _bump_next_set(target_reps: List[int], step: int) -> List[int]:
    """Advance the ramp by `step` reps on the first set that hasn't caught up.

    The lowest current value is the "not yet bumped" baseline; the first set
    still at that baseline is the next one to advance. Once every set is
    equal again, the ramp has completed a lap and the next call starts a new
    one from set 1.
    """
    bumped = list(target_reps)
    index = bumped.index(min(bumped))
    bumped[index] += step
    return bumped


def _hit_target(exercise_row: Dict[str, Any]) -> bool:
    """Whether the user logged every prescribed set at (or above) its target
    reps, in a session they actually completed."""
    if exercise_row.get("missed"):
        return False
    sets = exercise_row.get("sets") or 1
    target_reps = _parse_target_reps(exercise_row.get("reps"), sets)
    completed = {
        log["set_number"]: log["completed_reps"]
        for log in exercise_row.get("session_exercise_set_logs") or []
    }
    return all(completed.get(number, 0) >= target for number, target in enumerate(target_reps, start=1))


def _performed_reps(exercise_row: Dict[str, Any], target_reps: List[int]) -> List[int]:
    """Per-set reps the user actually logged, falling back to a set's target
    where that set was never logged (there is nothing better to go on)."""
    completed = {
        log["set_number"]: log["completed_reps"]
        for log in exercise_row.get("session_exercise_set_logs") or []
    }
    return [completed.get(number, target) for number, target in enumerate(target_reps, start=1)]


def _held_target_two_weeks(
    exercise_row: Dict[str, Any], previous_row: Optional[Dict[str, Any]]
) -> bool:
    """Whether the user hit the same per-set targets on this exercise two
    weeks running: this week's row and the previous plan's row for the same
    day and exercise both have the same targets, both fully hit. No previous
    row (first week, exercise swapped in, or day absent) means no streak."""
    if previous_row is None or not _hit_target(exercise_row) or not _hit_target(previous_row):
        return False
    return _parse_target_reps(previous_row.get("reps"), previous_row.get("sets") or 1) == _parse_target_reps(
        exercise_row.get("reps"), exercise_row.get("sets") or 1
    )


def _compute_progressed_reps(
    exercise_row: Dict[str, Any],
    injury_multiplier: Optional[float] = None,
    previous_row: Optional[Dict[str, Any]] = None,
    is_time_based: bool = False,
    max_reps: Optional[int] = None,
) -> Tuple[List[int], bool]:
    """Next plan's per-set target reps list for one session_exercises row,
    and whether it has outgrown the exercise (`advance`).

    Driven by the reported RPE and by whether every set's target was hit:
      - RPE 10 (hard), or any set short of its prescribed reps: every set
        drops by 1 from what the user actually *performed* on it (see
        _performed_reps), not from what was prescribed.
      - RPE 8 (correct): the ramp advances by 1 rep, one set at a time (see
        _bump_next_set) — only the next not-yet-bumped set goes up this week.
      - RPE 6 (too easy): every set goes to what she actually *performed* on
        it plus 1 rep (5 s for a timed hold) — e.g. targets 11, 10, 10, done
        11, 11, 11 -> 12, 12, 12. (Only reached with every target met, so
        each performed set is at least its target.)

    Going up on RPE 8 additionally requires the user to have hit the
    targets two weeks in a row (_held_target_two_weeks, with previous_row
    being the previous plan's row for the same day and exercise); otherwise
    last week's targets are copied forward unchanged. RPE 6 goes up straight
    away, with no hold — she said it was too easy. Coming down (RPE 10,
    missing RPE, injury) is never held back either.

    A missing RPE counts as RPE 8 (correct) when every set hit its target,
    and RPE 10 otherwise. An injury_multiplier below 1.0 (the exercise loads
    a joint the user has reported pain in — see
    _injury_multiplier_for_exercise) is always treated as RPE 10 regardless
    of what was reported — an injury caps volume outright.

    An exercise from a missed session (see is_session_missed) carries its
    targets forward unchanged rather than taking the missing-RPE path: the
    user didn't struggle with it, they just didn't do it. An injury still
    overrides this, dropping 1 from the prescribed targets (nothing was
    performed to go on).

    Going up never takes a set past the exercise's `max_reps` (when given):
    the bumped set is capped there. Once every set is already at `max_reps`
    and she earns another increase, the targets are returned unchanged with
    `advance` True — _apply_rep_bounds then swaps the exercise for its
    progression (or, with no progression edge, it stays at the max).

    For a timed exercise (is_time_based — targets are seconds held) the steps
    are TIMED_CORRECT_STEP / TIMED_EASY_STEP / TIMED_HARD_STEP seconds instead
    of 1 / 2 / 1 reps; the rules are otherwise identical.
    """
    if is_time_based:
        correct_step, easy_step, hard_step = TIMED_CORRECT_STEP, TIMED_EASY_STEP, TIMED_HARD_STEP
    else:
        correct_step, easy_step, hard_step = PROGRESSION_CORRECT_STEP, PROGRESSION_EASY_STEP, PROGRESSION_HARD_STEP
    sets = exercise_row.get("sets") or 1
    target_reps = _parse_target_reps(exercise_row.get("reps"), sets)

    if injury_multiplier is not None and injury_multiplier < 1.0:
        rpe_bucket = RPE_HARD
    elif exercise_row.get("missed"):
        return target_reps, False
    else:
        reported_rpe = (exercise_row.get("session_exercise_rpe") or {}).get("rpe")
        if reported_rpe is not None:
            rpe_bucket = _nearest_rpe_bucket(reported_rpe)
        elif _hit_target(exercise_row):
            rpe_bucket = PROGRESSION_UNRATED_HIT_RPE
        else:
            rpe_bucket = PROGRESSION_FALLBACK_RPE

    missed = bool(exercise_row.get("missed"))
    if rpe_bucket == RPE_HARD or not (missed or _hit_target(exercise_row)):
        base_reps = target_reps if missed else _performed_reps(exercise_row, target_reps)
        return [max(PROGRESSION_MIN_REPS, r - hard_step) for r in base_reps], False
    if rpe_bucket == RPE_TOO_EASY:
        if max_reps is not None and min(target_reps) >= max_reps:
            return target_reps, True
        bumped = [r + easy_step for r in _performed_reps(exercise_row, target_reps)]
        if max_reps is not None:
            bumped = [min(r, max_reps) for r in bumped]
        return bumped, False
    if _held_target_two_weeks(exercise_row, previous_row):
        step = correct_step
    else:
        return target_reps, False
    if max_reps is None:
        return _bump_next_set(target_reps, step), False
    if min(target_reps) >= max_reps:
        return target_reps, True
    return [min(r, max_reps) for r in _bump_next_set(target_reps, step)], False


class WorkoutPlanRepository:
    """Persists generated user profiles and workout sessions.

    Separate from WorkoutRepository (the exercise-library reader shared with
    ExerciseCsvRepository) since this handles unrelated, per-user generated
    data rather than static reference data.
    """

    def __init__(self, client: Optional[Client] = None):
        if client is not None:
            self.client = client
        else:
            url = os.environ.get("SUPABASE_URL")
            key = os.environ.get("SUPABASE_KEY")
            self.client = create_client(url, key)
        # (fetched at, circuit) — see _cardio_circuit.
        self._circuit_cache: Optional[Tuple[float, List[dict]]] = None

    def upsert_user_profile(
        self,
        user_id: str,
        profile: Dict[str, Any],
        name: Optional[str] = None,
        gender: Optional[str] = None,
    ) -> dict:
        """Upsert the user's generated profile. `name` (the client's display
        name) and `gender` are only written when given, so regenerating a
        profile without them keeps what's already on file."""
        row = {
            "user_id": user_id,
            "profile": profile,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if name is not None:
            row["name"] = name
        if gender is not None:
            row["gender"] = gender
        result = self.client.table("user_profiles").upsert(row, on_conflict="user_id").execute().data
        return result[0]

    def get_profile(self, user_id: str) -> Optional[dict]:
        rows = (
            self.client.table("user_profiles")
            .select("profile")
            .eq("user_id", user_id)
            .execute()
            .data
        )
        return rows[0]["profile"] if rows else None

    def get_gender(self, user_id: str) -> Optional[str]:
        rows = (
            self.client.table("user_profiles")
            .select("gender")
            .eq("user_id", user_id)
            .execute()
            .data
        )
        return rows[0]["gender"] if rows else None

    def user_exists(self, user_id: str) -> bool:
        rows = (
            self.client.table("user_profiles")
            .select("user_id")
            .eq("user_id", user_id)
            .execute()
            .data
        )
        return bool(rows)

    def get_session(self, session_id: int) -> Optional[dict]:
        """One day session, with its plan's owner/type/completion nested
        under "plans", or None if it doesn't exist."""
        rows = (
            self.client.table("sessions")
            .select("*, plans(user_id, plan_type, completed)")
            .eq("id", session_id)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def upsert_joint_pain(self, user_id: str, joint_pains: List[Dict[str, Any]]) -> List[dict]:
        """Upsert one or more (user, joint) pain_level rows into user_joint_pain.

        joint_pains is a list of {"joint_id": int, "pain_level": str}. Keyed
        by the table's (user_id, joint_id) unique constraint, so re-reporting
        pain for a joint already on file overwrites it rather than
        duplicating.
        """
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            {
                "user_id": user_id,
                "joint_id": jp["joint_id"],
                "pain_level": jp["pain_level"],
                "updated_at": now,
            }
            for jp in joint_pains
        ]
        return (
            self.client.table("user_joint_pain")
            .upsert(rows, on_conflict="user_id,joint_id")
            .execute()
            .data
        )

    def delete_joint_pain(self, user_id: str, joint_id: int) -> bool:
        """Delete the (user, joint) pain row, if one exists.

        Returns whether a row was actually deleted.
        """
        result = (
            self.client.table("user_joint_pain")
            .delete()
            .eq("user_id", user_id)
            .eq("joint_id", joint_id)
            .execute()
            .data
        )
        return bool(result)

    def get_session_analysis(self, session_id: int) -> Optional[dict]:
        """Fetch the workout_analysis_consumer-generated summary for a session, if ready."""
        rows = (
            self.client.table("session_analysis")
            .select("analysis, audio_url")
            .eq("session_id", session_id)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def get_unfinished_plan(self, user_id: str, close_if_resolved: bool = True) -> Optional[dict]:
        """The user's unfinished plan with its reconstructed schedule.

        If every one of its sessions is resolved — completed, or missed
        because its date passed (is_session_missed) — the plan is closed out
        here and auto-progressed (mark_plan_completed), and the new plan is
        returned instead. This is what moves a user on from a week whose last
        session(s) they missed, without any scheduled job. The new plan never
        starts in the past, so this closes at most one plan per call.
        """
        plans = (
            self.client.table("plans")
            .select("*")
            .eq("user_id", user_id)
            .eq("completed", False)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        if not plans:
            return None
        plan = plans[0]

        sessions = self._fetch_plan_sessions(plan["id"], PLAN_SESSIONS_SELECT)
        today = app_today()
        if close_if_resolved and sessions and all(
            s.get("completed_at") or is_session_missed(s, today) for s in sessions
        ):
            # None means a concurrent request closed it first — either way,
            # re-read whatever is unfinished now.
            self.mark_plan_completed(plan["id"])
            return self.get_unfinished_plan(user_id, close_if_resolved=False)

        return {
            "id": plan["id"],
            "completed": plan["completed"],
            "plan": self._reconstruct_plan(plan, sessions),
            "workouts": self._workout_entries(plan, sessions),
            "sessions": {
                s["day_number"]: {
                    "id": s["id"],
                    "kind": s.get("kind") or KIND_STRENGTH,
                    "scheduled_date": s["scheduled_date"],
                    "started_at": s.get("started_at"),
                    "completed_at": s.get("completed_at"),
                }
                for s in sessions
            },
        }

    def _fetch_plan_sessions(self, plan_id: int, select: str) -> List[dict]:
        return (
            self.client.table("sessions")
            .select(select)
            .eq("plan_id", plan_id)
            .order("day_number")
            .execute()
            .data
        )

    def _insert_sessions(
        self, plan_id: int, dates_by_day: Dict[int, date],
        cardio_days: Tuple[int, ...] = (), cardio_level: Tuple[int, int] = CARDIO_START,
    ) -> Dict[int, int]:
        """Insert one sessions row per (day_number, scheduled_date) and
        return {day_number: session id}. Days in cardio_days become cardio
        sessions at cardio_level (rounds, seconds per exercise); the rest
        are strength sessions."""
        if not dates_by_day:
            return {}
        rows = []
        for day_number, scheduled in sorted(dates_by_day.items()):
            row = {"plan_id": plan_id, "day_number": day_number, "scheduled_date": scheduled.isoformat()}
            if day_number in cardio_days:
                row.update({
                    "kind": KIND_CARDIO,
                    "cardio_rounds": cardio_level[0],
                    "cardio_work_seconds": cardio_level[1],
                })
            else:
                row["kind"] = KIND_STRENGTH
            rows.append(row)
        inserted = self.client.table("sessions").insert(rows).execute().data
        return {row["day_number"]: row["id"] for row in inserted}

    @staticmethod
    def _cardio_days_for(plan_type: Optional[str], strength_days) -> Tuple[int, ...]:
        """The plan type's cardio days, minus any that already hold a
        strength session (never the case for the built-in templates)."""
        return tuple(d for d in CARDIO_DAYS.get(plan_type or "", ()) if d not in set(strength_days))

    def _cardio_circuit(self) -> List[dict]:
        """The active cardio_exercises in circuit order, each as
        {id, name, video_url, poster_url}. Cached for a few minutes, since
        every dashboard load needs it and it rarely changes."""
        now = time.monotonic()
        if self._circuit_cache and now - self._circuit_cache[0] < CARDIO_CIRCUIT_TTL_SECONDS:
            return self._circuit_cache[1]
        rows = (
            self.client.table("cardio_exercises")
            .select("id, name, video_path, poster_path, position")
            .eq("active", True)
            .order("position")
            .execute()
            .data
        )
        circuit = [
            {
                "id": row["id"],
                "name": row["name"],
                "video_url": _cardio_media_url(row.get("video_path")),
                "poster_url": _cardio_media_url(row.get("poster_path")),
            }
            for row in sorted(rows, key=lambda r: r["position"])
        ]
        self._circuit_cache = (now, circuit)
        return circuit

    def _cardio_block(self, session: dict) -> Dict[str, Any]:
        """What the PWA needs to run (or show) a cardio session.
        `work_seconds` is what she actually does: 70% of the planned
        `planned_work_seconds` on a period day (is_period)."""
        rounds, planned = session_level(session)
        work_seconds = actual_work_seconds(session)
        circuit = self._cardio_circuit()
        return {
            "rounds": rounds,
            "work_seconds": work_seconds,
            "planned_work_seconds": planned,
            "is_period": bool(session.get("is_period")),
            "rating": session.get("cardio_rating"),
            "get_ready_seconds": CARDIO_GET_READY_SECONDS,
            # A third of the exercise time she actually does (so a period
            # day's shorter exercises get shorter rests too).
            "exercise_rest_seconds": exercise_rest_seconds(work_seconds),
            "round_rest_seconds": CARDIO_ROUND_REST_SECONDS,
            "estimated_seconds": estimated_seconds((rounds, work_seconds), len(circuit)),
            "exercises": circuit,
            **_cardio_log(session, rounds * len(circuit)),
        }

    def get_previous_plan_workouts(self, user_id: str, before_plan_id: int) -> List[dict]:
        """The workouts (see _workout_entries) of the user's most recently
        completed plan other than before_plan_id, so the dashboard can show
        last week's workouts early in a new plan. [] if there's no such plan."""
        plans = (
            self.client.table("plans")
            .select("*")
            .eq("user_id", user_id)
            .eq("completed", True)
            .neq("id", before_plan_id)
            .order("completed_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        if not plans:
            return []
        plan = plans[0]
        return self._workout_entries(plan, self._fetch_plan_sessions(plan["id"], PLAN_SESSIONS_SELECT))

    def get_last_completed_plan(self, user_id: str) -> Optional[dict]:
        plans = (
            self.client.table("plans")
            .select("*")
            .eq("user_id", user_id)
            .eq("completed", True)
            .order("completed_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        if not plans:
            return None
        plan = plans[0]
        return {"plan": plan, "sessions": self._fetch_plan_sessions(plan["id"], PROGRESSION_SESSIONS_SELECT)}

    def get_injury_multiplier(
        self, exercise_id: int, joint_id: int, pain_level: PainLevel
    ) -> float:
        """Injury multiplier for one (exercise, joint) pair at a given pain level.

        Looks up the exercise's joint_load classification (high/mid/low/nil)
        from exercise_loaded_joints and maps it through
        JOINT_LOAD_INJURY_MULTIPLIERS (the Corrected Joint Load Factors
        table). No matching row is treated the same as "nil" (the exercise
        doesn't load that joint), so it returns 1.0 rather than excluding.
        """
        rows = (
            self.client.table("exercise_loaded_joints")
            .select("joint_load")
            .eq("exercise_id", exercise_id)
            .eq("joint_id", joint_id)
            .execute()
            .data
        )
        joint_load = rows[0]["joint_load"] if rows else "nil"
        return JOINT_LOAD_INJURY_MULTIPLIERS[pain_level][joint_load]

    def _fetch_user_joint_pain(self, user_id: str) -> Dict[int, PainLevel]:
        """joint_id -> reported PainLevel for this user, from user_joint_pain."""
        rows = (
            self.client.table("user_joint_pain")
            .select("joint_id, pain_level")
            .eq("user_id", user_id)
            .execute()
            .data
        )
        return {row["joint_id"]: PainLevel(row["pain_level"]) for row in rows}

    def _fetch_loaded_joints(self, exercise_ids: List[int]) -> Dict[int, Dict[int, str]]:
        """exercise_id -> {joint_id: joint_load}, batched into one query."""
        if not exercise_ids:
            return {}
        rows = (
            self.client.table("exercise_loaded_joints")
            .select("exercise_id, joint_id, joint_load")
            .in_("exercise_id", list(set(exercise_ids)))
            .execute()
            .data
        )
        loaded: Dict[int, Dict[int, str]] = defaultdict(dict)
        for row in rows:
            loaded[row["exercise_id"]][row["joint_id"]] = row["joint_load"]
        return loaded

    @staticmethod
    def _injury_multiplier_for_exercise(
        exercise_id: int,
        loaded_joints_by_exercise: Dict[int, Dict[int, str]],
        user_joint_pain: Dict[int, PainLevel],
    ) -> Optional[float]:
        """Most conservative Corrected Joint Load Factor across this
        exercise's loaded joints that the user has reported pain in.

        Returns None (fall back to the RPE-based multiplier) if the exercise
        loads no joint the user has reported pain in. When it does load more
        than one, the lowest multiplier wins — an injury in any joint the
        exercise stresses should cap volume, not average out against joints
        that are fine.
        """
        multipliers = [
            JOINT_LOAD_INJURY_MULTIPLIERS[user_joint_pain[joint_id]][joint_load]
            for joint_id, joint_load in loaded_joints_by_exercise.get(exercise_id, {}).items()
            if joint_load != "nil" and joint_id in user_joint_pain
        ]
        return min(multipliers) if multipliers else None

    def _fetch_exercise_rep_bounds(self, exercise_ids: List[int]) -> Dict[int, dict]:
        """id -> {min_reps, max_reps, is_time_based} for the given exercises,
        batched into one query."""
        if not exercise_ids:
            return {}
        rows = (
            self.client.table("exercises")
            .select("id, min_reps, max_reps, is_time_based")
            .in_("id", list(set(exercise_ids)))
            .execute()
            .data
        )
        return {row["id"]: row for row in rows}

    def _fetch_regressions(self, exercise_ids: List[int]) -> Dict[int, int]:
        """from_exercise_id -> to_exercise_id for the "lack of strength" regression edge."""
        if not exercise_ids:
            return {}
        rows = (
            self.client.table("exercise_relationships")
            .select("from_exercise_id, to_exercise_id")
            .eq("type", "regression")
            .ilike("reason", f"%{REGRESSION_REASON_FILTER}%")
            .in_("from_exercise_id", list(set(exercise_ids)))
            .execute()
            .data
        )
        return {row["from_exercise_id"]: row["to_exercise_id"] for row in rows}

    def _fetch_progressions(self, exercise_ids: List[int]) -> Dict[int, int]:
        """from_exercise_id -> to_exercise_id for the progression edge."""
        if not exercise_ids:
            return {}
        rows = (
            self.client.table("exercise_relationships")
            .select("from_exercise_id, to_exercise_id")
            .eq("type", "progression")
            .in_("from_exercise_id", list(set(exercise_ids)))
            .execute()
            .data
        )
        return {row["from_exercise_id"]: row["to_exercise_id"] for row in rows}

    def _apply_rep_bounds(
        self, items: List[Dict[str, Any]], regress_to: str = "max_reps"
    ) -> List[Dict[str, Any]]:
        """Swap or clamp each item against its exercise's own rep bounds.

        Each item is {"exercise_id", "reps": per-set target list, "rep_range"}
        plus an optional "advance" flag (from _compute_progressed_reps: every
        set is at `max_reps` and she earned another increase). If any set is
        below the exercise's `min_reps` it is swapped for its "lack of
        strength" regression with every set at that exercise's `regress_to`
        bound (`max_reps` by default — the easier exercise starts at the top
        of its range); with no regression edge every set is set to
        `min_reps`. An item flagged "advance" is swapped for its progression
        with every set at that exercise's `min_reps`; with no progression
        edge it stays where it is. Any set over `max_reps` is capped there on
        its own (sets below it are left alone).
        `rep_range` follows a swapped-in exercise's own min-max. Returns the
        items in the same order, same shape.
        """
        rep_bounds = self._fetch_exercise_rep_bounds([item["exercise_id"] for item in items])

        below_min_ids = [
            item["exercise_id"]
            for item in items
            if item["exercise_id"] in rep_bounds
            and min(item["reps"]) < rep_bounds[item["exercise_id"]]["min_reps"]
        ]
        advance_ids = [item["exercise_id"] for item in items if item.get("advance")]
        regressions = self._fetch_regressions(below_min_ids)
        progressions = self._fetch_progressions(advance_ids)

        replacement_ids = set(regressions.values()) | set(progressions.values())
        replacement_bounds = self._fetch_exercise_rep_bounds(list(replacement_ids))

        resolved = []
        for item in items:
            exercise_id = item["exercise_id"]
            rep_range = item["rep_range"]
            bounds = rep_bounds.get(exercise_id)
            next_reps_list = item["reps"]

            if bounds is not None and min(next_reps_list) < bounds["min_reps"]:
                target_id = regressions.get(exercise_id)
                if target_id is not None:
                    exercise_id = target_id
                    target_bounds = replacement_bounds[target_id]
                    next_reps_list = [target_bounds[regress_to]] * len(next_reps_list)
                    rep_range = f"{target_bounds['min_reps']}-{target_bounds['max_reps']}"
                else:
                    next_reps_list = [bounds["min_reps"]] * len(next_reps_list)
            elif item.get("advance") and progressions.get(exercise_id) is not None:
                target_id = progressions[exercise_id]
                exercise_id = target_id
                target_bounds = replacement_bounds[target_id]
                next_reps_list = [target_bounds["min_reps"]] * len(next_reps_list)
                rep_range = f"{target_bounds['min_reps']}-{target_bounds['max_reps']}"
            elif bounds is not None and max(next_reps_list) > bounds["max_reps"]:
                next_reps_list = [min(r, bounds["max_reps"]) for r in next_reps_list]

            resolved.append({"exercise_id": exercise_id, "reps": next_reps_list, "rep_range": rep_range})
        return resolved

    def _progression_sources(
        self, source_plan: dict, source_sessions: List[dict]
    ) -> tuple[List[dict], Dict[tuple, dict]]:
        """The sessions progression should learn from, one per day.

        A session done during a period ran at reduced reps, so it is never
        used. For each day this is the latest non-period session (the source
        plan's own, else the same day's session in the nearest ancestor plan
        via parent_plan_id, up to MAX_PROGRESSION_HOPS back), plus the
        completed non-period session before it, whose rows (keyed
        (day_number, exercise_id)) feed the two-week hold check. Missed
        sessions are skipped for that second one just like period ones: a
        missed week carries its targets forward unchanged, so the week
        before it is the one to compare against.

        A day with no non-period session anywhere in that history falls back
        to the period session itself, carried forward unchanged (its targets
        are already reduced, but there is nothing better to go on).
        """
        found: Dict[int, List[dict]] = {s["day_number"]: [] for s in source_sessions}
        for session in source_sessions:
            if not session.get("is_period"):
                found[session["day_number"]].append(session)

        plan_id = source_plan.get("parent_plan_id")
        hops = 0
        while plan_id and hops < MAX_PROGRESSION_HOPS and any(len(v) < 2 for v in found.values()):
            for session in self._fetch_plan_sessions(plan_id, PROGRESSION_SESSIONS_SELECT):
                sessions = found.get(session["day_number"])
                if (
                    sessions is not None
                    and len(sessions) < 2
                    and not session.get("is_period")
                    # The streak's earlier week must have been done, not missed.
                    and (not sessions or session.get("completed_at"))
                ):
                    sessions.append(session)
            parent = (
                self.client.table("plans").select("parent_plan_id").eq("id", plan_id).execute().data
            )
            plan_id = parent[0]["parent_plan_id"] if parent else None
            hops += 1

        sources = []
        for session in source_sessions:
            latest = found[session["day_number"]]
            # No completed_at -> its rows count as missed, i.e. carry forward.
            sources.append(latest[0] if latest else {**session, "completed_at": None})
        previous_rows = {
            (row["day_number"], row["exercise_id"]): row
            for earlier in found.values()
            for row in _flatten_session_exercises(earlier[1:2])
        }
        return sources, previous_rows

    def _cardio_next_level(self, source_plan: dict, source_sessions: List[dict]) -> Tuple[int, int]:
        """Next week's cardio level (rounds, seconds per exercise) from the
        source plan's cardio sessions (backend.cardio.next_level). A plan
        with none (from before cardio existed) starts at CARDIO_START.
        Period sessions don't vote (week_outcome), and the level read is the
        stored, planned one, so a period week never lowers it.

        A medium week only steps up when the previous counted week — the
        nearest ancestor plan with a completed non-period cardio session,
        skipping weeks whose cardio was all missed or on her period — was
        also medium at this level.
        """
        cardio = sorted((s for s in source_sessions if is_cardio(s)), key=lambda s: s["day_number"])
        if not cardio:
            return CARDIO_START
        current = session_level(cardio[0])
        outcome = week_outcome(cardio)
        previous_week = None
        if outcome == MEDIUM:
            previous_week = self._previous_cardio_week(source_plan.get("parent_plan_id"))
        return next_level(current, outcome, previous_week)

    def _previous_cardio_week(self, plan_id: Optional[int]) -> Optional[Tuple[str, Tuple[int, int]]]:
        """(outcome, level) of the nearest plan, from plan_id up through
        parent_plan_id, with a completed cardio session. None if there's
        none within MAX_PROGRESSION_HOPS, or the chain reaches a plan from
        before cardio existed."""
        hops = 0
        while plan_id and hops < MAX_PROGRESSION_HOPS:
            cardio = sorted(
                (s for s in self._fetch_plan_sessions(plan_id, CARDIO_HISTORY_SELECT) if is_cardio(s)),
                key=lambda s: s["day_number"],
            )
            if not cardio:
                return None
            outcome = week_outcome(cardio)
            if outcome is not None:
                return outcome, session_level(cardio[0])
            parent = self.client.table("plans").select("parent_plan_id").eq("id", plan_id).execute().data
            plan_id = parent[0]["parent_plan_id"] if parent else None
            hops += 1
        return None

    def regenerate_current_plan(self, user_id: str) -> dict:
        """Rebuild the user's current (unfinished) week: delete it and run
        progression again from the plan it was progressed from, keeping its
        calendar dates. For when progression's rules or its inputs (e.g. RPE)
        changed after the week was generated.

        Raises PlanRegenerationError when there's no current week, it isn't a
        progression of an earlier plan, or any of its workouts was already
        started (deleting it would lose what was logged).
        """
        current = self.get_unfinished_plan(user_id)
        if current is None:
            raise PlanRegenerationError("This client has no current week to rebuild.")
        plan_row = self.client.table("plans").select("*").eq("id", current["id"]).execute().data[0]
        parent_id = plan_row.get("parent_plan_id")
        if parent_id is None:
            raise PlanRegenerationError(
                "This is the client's first plan, so there's no earlier week to progress from."
            )
        if any(s.get("started_at") for s in current["sessions"].values()):
            raise PlanRegenerationError(
                "A workout in this week has already been started, so it can't be rebuilt."
            )
        parents = self.client.table("plans").select("*").eq("id", parent_id).execute().data
        if not parents:
            raise PlanRegenerationError("The week this one was progressed from no longer exists.")
        parent_sessions = self._fetch_plan_sessions(parent_id, PROGRESSION_SESSIONS_SELECT)
        start_date = min(
            date.fromisoformat(s["scheduled_date"]) - timedelta(days=day_number - 1)
            for day_number, s in current["sessions"].items()
        ) if current["sessions"] else None

        # Delete first: plans_one_unfinished_per_user allows only one
        # unfinished plan. If progression then fails, the parent is still
        # completed, so retrying (or POST .../progress-plan) rebuilds it.
        self.client.table("plans").delete().eq("id", current["id"]).execute()
        return self.create_progressed_plan(user_id, parents[0], parent_sessions, start_date=start_date)

    def create_progressed_plan(
        self, user_id: str, source_plan: dict, source_sessions: List[dict],
        start_date: Optional[date] = None,
    ) -> dict:
        """Insert the next plan by carrying forward source_plan's sessions and
        their exercises, recalculating each exercise row's `reps` via
        _compute_progressed_reps.

        source_sessions are the source plan's sessions rows (selected with
        PROGRESSION_SESSIONS_SELECT, so each has its session_exercises nested).
        Each new session keeps its source's day_number and is scheduled
        PROGRESSION_SCHEDULE_OFFSET (one week) after it — unless that week
        would start before today (the source plan closed late, e.g. a user
        returning after a break), in which case the new plan starts today
        so it isn't born with its sessions already missed. A given start_date
        (regenerate_current_plan keeping a week's dates) overrides both.

        Exercises from a missed session carry forward unchanged (see
        _compute_progressed_reps), as do exercises rated RPE 8 (or unrated)
        that haven't yet held their targets for two weeks running — the
        previous plan
        (source_plan["parent_plan_id"]) supplies last week's row for that
        check.

        Each exercise's reps target is computed by _compute_progressed_reps,
        using an injury multiplier (_injury_multiplier_for_exercise) in place
        of the RPE-based one wherever the exercise loads a joint the user has
        reported pain in (user_joint_pain), and the ordinary RPE-based
        multiplier otherwise.

        If the recalculated reps falls below the exercise's own `min_reps`
        (from `exercises`), the exercise is swapped for its "lack of
        strength" regression (`exercise_relationships`) and reps is set to
        that regression's own `max_reps`. Going up, each set is capped at
        `max_reps`; once every set is at `max_reps` and she earns another
        increase, the exercise is swapped for its progression and reps is set
        to *that* exercise's `min_reps`. If no matching regression/progression
        edge exists, the exercise is kept as-is: every set goes to
        `min_reps`, or stays at `max_reps`. `rep_range` is refreshed to match a
        swapped-in exercise's own min-max (per the "matched catalog row's
        f'{min_reps}-{max_reps}'" convention); everything else
        (category/slot_label/sets/note, and the day via its session) is
        carried over unchanged.

        This applies uniformly regardless of *why* reps dropped, so an
        injury-driven low multiplier can swap an exercise to its regression
        exactly like a poor-performance one would.
        """
        completed_at = source_plan.get("completed_at")
        plan_row = {
            "user_id": user_id,
            "parent_plan_id": source_plan.get("id"),
            "plan_type": source_plan.get("plan_type"),
            "plan_selection_reason": (
                f"Progressive overload from the plan completed on {completed_at}."
                if completed_at
                else "Progressive overload from the previous completed plan."
            ),
            "medical_clearance_warning": source_plan.get("medical_clearance_warning"),
            "coach_notes": source_plan.get("coach_notes"),
            "safety_summary": source_plan.get("safety_summary"),
        }
        plan = self.client.table("plans").insert(plan_row).execute().data[0]
        # Cardio sessions progress as a week (see _cardio_next_level), not
        # per exercise row, so the strength machinery below never sees them.
        strength_sessions = [s for s in source_sessions if not is_cardio(s)]
        session_ids = {}
        if source_sessions:
            source_start = min(
                date.fromisoformat(s["scheduled_date"]) - timedelta(days=s["day_number"] - 1)
                for s in source_sessions
            )
            if start_date is None:
                start_date = max(source_start + PROGRESSION_SCHEDULE_OFFSET, app_today())
            strength_days = [s["day_number"] for s in strength_sessions]
            # A plan from before cardio existed gets its cardio days here too.
            cardio_days = self._cardio_days_for(source_plan.get("plan_type"), strength_days)
            session_ids = self._insert_sessions(
                plan["id"],
                {d: scheduled_date_for(start_date, d) for d in (*strength_days, *cardio_days)},
                cardio_days=cardio_days,
                cardio_level=self._cardio_next_level(source_plan, source_sessions),
            )
        sources, previous_rows = self._progression_sources(source_plan, strength_sessions)
        exercise_rows = _flatten_session_exercises(sources)

        user_joint_pain = self._fetch_user_joint_pain(user_id)
        loaded_joints_by_exercise = self._fetch_loaded_joints(
            [row["exercise_id"] for row in exercise_rows]
        )
        exercise_info = self._fetch_exercise_rep_bounds([row["exercise_id"] for row in exercise_rows])
        computed = {
            row["id"]: _compute_progressed_reps(
                row,
                self._injury_multiplier_for_exercise(
                    row["exercise_id"], loaded_joints_by_exercise, user_joint_pain
                ),
                previous_rows.get((row["day_number"], row["exercise_id"])),
                bool((exercise_info.get(row["exercise_id"]) or {}).get("is_time_based")),
                (exercise_info.get(row["exercise_id"]) or {}).get("max_reps"),
            )
            for row in exercise_rows
        }
        resolved = self._apply_rep_bounds([
            {
                "exercise_id": row["exercise_id"],
                "reps": computed[row["id"]][0],
                "advance": computed[row["id"]][1],
                "rep_range": row.get("rep_range"),
            }
            for row in exercise_rows
        ])

        new_exercise_rows = []
        for row, item in zip(exercise_rows, resolved):
            new_exercise_rows.append({
                "session_id": session_ids[row["day_number"]],
                "exercise_id": item["exercise_id"],
                "category": row["category"],
                "slot_label": row.get("slot_label"),
                "sets": row.get("sets"),
                "reps": ",".join(str(r) for r in item["reps"]),
                "rep_range": item["rep_range"],
                "note": row.get("note"),
            })
        if new_exercise_rows:
            self.client.table("session_exercises").insert(new_exercise_rows).execute()

        return plan

    def create_plan(self, user_id: str, plan: Dict[str, Any], start_date: date) -> dict:
        """Insert a brand-new plan: the plans row, one sessions row per
        training day (day N scheduled N-1 days after start_date), and each
        day's prescribed exercises."""
        plan_row = {
            "user_id": user_id,
            "parent_plan_id": None,
            "plan_type": plan.get("plan_type"),
            "plan_selection_reason": plan.get("plan_selection_reason"),
            "medical_clearance_warning": plan.get("medical_clearance_warning"),
            "coach_notes": plan.get("coach_notes"),
            "safety_summary": plan.get("safety_summary"),
        }
        created = self.client.table("plans").insert(plan_row).execute().data[0]

        training_days = [day for day in plan.get("schedule", []) if not day.get("is_rest_day")]
        cardio_days = self._cardio_days_for(plan.get("plan_type"), [d["day_number"] for d in training_days])
        session_ids = self._insert_sessions(
            created["id"],
            {
                day_number: scheduled_date_for(start_date, day_number)
                for day_number in (*(d["day_number"] for d in training_days), *cardio_days)
            },
            cardio_days=cardio_days,
        )

        exercise_rows = []
        for day in training_days:
            for category in ("primary", "secondary"):
                for ex in day.get(category, []):
                    exercise_rows.append({
                        "session_id": session_ids[day["day_number"]],
                        "exercise_id": ex["exercise_id"],
                        "category": category,
                        "slot_label": ex.get("slot"),
                        "sets": ex.get("sets"),
                        "reps": ex.get("reps"),
                        "rep_range": ex.get("rep_range"),
                        "note": ex.get("note"),
                    })
        if exercise_rows:
            self.client.table("session_exercises").insert(exercise_rows).execute()

        return created

    def mark_plan_completed(self, plan_id: int) -> Optional[dict]:
        """Close out an unfinished plan and auto-progress it. Returns None if
        the plan doesn't exist or is already completed — the update only
        matches while completed is false, so two racing closes (e.g. the
        dashboard's lazy close and complete_session) progress it only once."""
        result = (
            self.client.table("plans")
            .update({"completed": True, "completed_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", plan_id)
            .eq("completed", False)
            .execute()
            .data
        )
        if not result:
            return None
        completed_plan = result[0]
        self._auto_progress(completed_plan)
        return completed_plan

    def _auto_progress(self, completed_plan: dict) -> None:
        """Generate the next week's plan as soon as this one is marked
        completed, so the user always has a next plan waiting without having
        to call POST /api/users/<user_id>/progress-plan themselves.

        Best-effort: the plan is already committed as completed regardless
        of whether this succeeds, so a failure here is logged and swallowed
        rather than surfaced as a failure of whatever request triggered the
        completion (session completion or the manual admin endpoint).
        """
        try:
            sessions = self._fetch_plan_sessions(completed_plan["id"], PROGRESSION_SESSIONS_SELECT)
            if _flatten_session_exercises(sessions):
                self.create_progressed_plan(completed_plan["user_id"], completed_plan, sessions)
        except Exception:
            logger.exception(
                "Failed to auto-generate progressed plan for user_id=%s after plan_id=%s completed",
                completed_plan.get("user_id"),
                completed_plan.get("id"),
            )

    def set_feedback_audio_path(self, session_id: int, path: str) -> None:
        """Point the session at its voice-feedback recording in storage."""
        self.client.table("sessions").update({"feedback_audio_path": path}).eq("id", session_id).execute()

    def get_session_exercise(self, session_exercise_id: int, session_id: Optional[int] = None) -> Optional[dict]:
        """{id, session_id, feedback_audio_path, skipped} of one
        session_exercises row, or None if it doesn't exist (or, given
        session_id, isn't in that session)."""
        query = (
            self.client.table("session_exercises")
            .select("id, session_id, feedback_audio_path, skipped")
            .eq("id", session_exercise_id)
        )
        if session_id is not None:
            query = query.eq("session_id", session_id)
        rows = query.execute().data
        return rows[0] if rows else None

    def set_exercise_feedback_audio_path(self, session_exercise_id: int, path: str) -> None:
        """Point one exercise of a session at its voice-note recording in storage."""
        (
            self.client.table("session_exercises")
            .update({"feedback_audio_path": path})
            .eq("id", session_exercise_id)
            .execute()
        )

    def start_session(self, session_id: int, is_period: bool = False) -> dict:
        """Stamp started_at on a session the first time it's started.

        started_at is never overwritten once set (the update only matches
        while it's still null), so re-entering a session the user already
        began doesn't reset its Total Time baseline. is_period is only acted
        on by that first start, so resuming never re-applies it.
        """
        values = {"started_at": datetime.now(timezone.utc).isoformat()}
        if is_period:
            values["is_period"] = True
        result = (
            self.client.table("sessions")
            .update(values)
            .eq("id", session_id)
            .is_("started_at", "null")
            .execute()
            .data
        )
        if result:
            if is_period:
                self._apply_period_adjustment(session_id)
                self._log_period(session_id)
            return result[0]
        return self.client.table("sessions").select("*").eq("id", session_id).execute().data[0]

    def _log_period(self, session_id: int) -> None:
        """Record today (in APP_TIMEZONE) as a period day for the session's
        user in user_period_logs. One row per (user, date), so answering yes
        on two sessions the same day logs it once."""
        user_id = ((self.get_session(session_id) or {}).get("plans") or {}).get("user_id")
        if user_id is None:
            return
        (
            self.client.table("user_period_logs")
            .upsert(
                {"user_id": user_id, "logged_on": app_today().isoformat(), "session_id": session_id},
                on_conflict="user_id,logged_on",
                ignore_duplicates=True,
            )
            .execute()
        )

    def _apply_period_adjustment(self, session_id: int) -> None:
        """Rewrite a period session's exercise rows in place to
        PERIOD_REP_FACTOR of their planned reps, swapping to the "lack of
        strength" regression at its `min_reps` (or clamping) where that drops
        below an exercise's `min_reps` (see _apply_rep_bounds)."""
        rows = (
            self.client.table("session_exercises")
            .select("id, exercise_id, sets, reps, rep_range")
            .eq("session_id", session_id)
            .execute()
            .data
        )
        resolved = self._apply_rep_bounds([
            {
                "exercise_id": row["exercise_id"],
                "reps": _scale_reps_for_period(_parse_target_reps(row.get("reps"), row.get("sets") or 1)),
                "rep_range": row.get("rep_range"),
            }
            for row in rows
        ], regress_to="min_reps")
        for row, item in zip(rows, resolved):
            (
                self.client.table("session_exercises")
                .update({
                    "exercise_id": item["exercise_id"],
                    "reps": ",".join(str(r) for r in item["reps"]),
                    "rep_range": item["rep_range"],
                })
                .eq("id", row["id"])
                .execute()
            )

    def log_set(
        self, session_id: int, session_exercise_id: int, set_number: int, completed_reps: int
    ) -> Optional[dict]:
        """Upsert the session_exercise_set_logs row for one (exercise, set_number).

        Ownership/bounds are validated with a read first (their outcome never
        changes after row creation, so no race there). Each set_number is its
        own row keyed by the (session_exercise_id, set_number) unique
        constraint, so logging two different sets back to back can't race the
        way a shared jsonb array could.

        Returns the upserted row, or None if session_exercise_id doesn't
        belong to session_id, the coach skipped it for this session, or
        set_number is out of range.
        """
        rows = (
            self.client.table("session_exercises")
            .select("sets, skipped")
            .eq("id", session_exercise_id)
            .eq("session_id", session_id)
            .execute()
            .data
        )
        if not rows or rows[0].get("skipped"):
            return None

        total_sets = rows[0].get("sets") or 0
        if set_number < 1 or set_number > total_sets:
            return None

        row = {
            "session_exercise_id": session_exercise_id,
            "set_number": set_number,
            "completed_reps": completed_reps,
        }
        result = (
            self.client.table("session_exercise_set_logs")
            .upsert(row, on_conflict="session_exercise_id,set_number")
            .execute()
            .data
        )
        return result[0] if result else None

    def log_rpe(self, session_id: int, session_exercise_id: int, rpe: int) -> Optional[dict]:
        """Upsert the session_exercise_rpe row for one exercise (one RPE per
        exercise per session). None if it isn't in the session or the coach
        skipped it."""
        rows = (
            self.client.table("session_exercises")
            .select("id, skipped")
            .eq("id", session_exercise_id)
            .eq("session_id", session_id)
            .execute()
            .data
        )
        if not rows or rows[0].get("skipped"):
            return None

        row = {"session_exercise_id": session_exercise_id, "rpe": rpe}
        result = (
            self.client.table("session_exercise_rpe")
            .upsert(row, on_conflict="session_exercise_id")
            .execute()
            .data
        )
        return result[0] if result else None

    def complete_session(self, session_id: int) -> Optional[dict]:
        session = self.get_session(session_id)
        if session is None:
            return None

        # False when re-completing (e.g. re-opening a finished workout's
        # summary): it earns no new grow points.
        newly_completed = session.get("completed_at") is None
        now = datetime.now(timezone.utc)
        # Defensive fallback: complete_session called without a prior start_session.
        started_at = session.get("started_at") or now.isoformat()
        (
            self.client.table("sessions")
            .update({"started_at": started_at, "completed_at": now.isoformat()})
            .eq("id", session_id)
            .execute()
        )

        exercise_rows = (
            self.client.table("session_exercises")
            .select("sets, skipped, session_exercise_set_logs(set_number)")
            .eq("session_id", session_id)
            .execute()
            .data
        )
        # Exercises the coach skipped for this session aren't part of it.
        exercise_rows = [row for row in exercise_rows if not row.get("skipped")]
        total_exercises = len(exercise_rows)
        exercises_completed = 0
        sets_completed = 0
        total_sets = 0
        for row in exercise_rows:
            prescribed = row.get("sets") or 0
            logged = len(row.get("session_exercise_set_logs") or [])
            total_sets += prescribed
            sets_completed += logged
            if prescribed and logged >= prescribed:
                exercises_completed += 1

        total_time_seconds = int((now - datetime.fromisoformat(started_at)).total_seconds())

        # The plan is done once every one of its sessions is completed or
        # missed (uncompleted and dated before today — see is_session_missed).
        # Skipped when the plan is already completed (a re-completed session),
        # so it isn't re-marked and auto-progressed twice.
        plan_completed = False
        if not (session.get("plans") or {}).get("completed"):
            still_open = (
                self.client.table("sessions")
                .select("id")
                .eq("plan_id", session["plan_id"])
                .is_("completed_at", "null")
                .gte("scheduled_date", app_today().isoformat())
                .execute()
                .data
            )
            if not still_open:
                plan_completed = self.mark_plan_completed(session["plan_id"]) is not None

        summary = {
            "session_id": session_id,
            "day_number": session["day_number"],
            "kind": session.get("kind") or KIND_STRENGTH,
            "total_time_seconds": total_time_seconds,
            "exercises_completed": exercises_completed,
            "total_exercises": total_exercises,
            "sets_completed": sets_completed,
            "total_sets": total_sets,
            "plan_completed": plan_completed,
            "newly_completed": newly_completed,
        }
        if is_cardio(session):
            # A cardio session has no session_exercises: it counts as the
            # whole circuit, every round of it.
            n_exercises = len(self._cardio_circuit())
            summary.update({
                "exercises_completed": n_exercises,
                "total_exercises": n_exercises,
                "rounds": session.get("cardio_rounds"),
                "work_seconds": actual_work_seconds(session),
                "rating": session.get("cardio_rating"),
                "is_period": bool(session.get("is_period")),
            })
        return summary

    def log_cardio_step(
        self, session: dict, round_number: int, position: int, part: str,
        actual_seconds: int, paused_seconds: int, skipped: bool,
    ) -> dict:
        """Record how one step of a cardio session went: the exercise at
        `position` (0-based, circuit order) of round `round_number`, or —
        part "rest" — the rest that followed it (the round rest after a
        round's last exercise). One session_cardio_logs row per exercise per
        round holds both; this upserts only the given part's columns, so the
        exercise and its rest can arrive in either order, and a re-run of
        the circuit overwrites the earlier attempt.

        The exercise name and planned seconds come from here, not the
        client: the circuit, and the session's level (70% on a period day).
        Raises CardioLogError when the step doesn't exist in this session.
        """
        if not is_cardio(session):
            raise CardioLogError("This isn't a cardio workout.")
        if part not in CARDIO_LOG_PARTS:
            raise CardioLogError("'part' must be 'exercise' or 'rest'.")
        circuit = self._cardio_circuit()
        rounds = session["cardio_rounds"]
        if not 1 <= round_number <= rounds:
            raise CardioLogError(f"'round' must be between 1 and {rounds}.")
        if not 0 <= position < len(circuit):
            raise CardioLogError(f"'position' must be between 0 and {len(circuit) - 1}.")
        for value in (actual_seconds, paused_seconds):
            if not 0 <= value <= CARDIO_LOG_MAX_SECONDS:
                raise CardioLogError(f"Seconds must be between 0 and {CARDIO_LOG_MAX_SECONDS}.")
        last_of_round = position == len(circuit) - 1
        if part == "rest" and last_of_round and round_number == rounds:
            raise CardioLogError("There's no rest after the last exercise.")

        work_seconds = actual_work_seconds(session)
        exercise = circuit[position]
        row = {
            "session_id": session["id"],
            "round": round_number,
            "position": position,
            # Always sent, so even a rest arriving first makes a valid row.
            "cardio_exercise_id": exercise["id"],
            "exercise_name": exercise["name"],
            "planned_seconds": work_seconds,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if part == "exercise":
            row.update({"actual_seconds": actual_seconds, "paused_seconds": paused_seconds, "skipped": skipped})
        else:
            row.update({
                "rest_planned_seconds": (
                    CARDIO_ROUND_REST_SECONDS if last_of_round else exercise_rest_seconds(work_seconds)
                ),
                "rest_actual_seconds": actual_seconds,
                "rest_paused_seconds": paused_seconds,
                "rest_skipped": skipped,
            })
        result = (
            self.client.table("session_cardio_logs")
            .upsert(row, on_conflict="session_id,round,position")
            .execute()
            .data
        )
        return result[0] if result else row

    def set_cardio_rating(self, session_id: int, rating: str) -> Optional[dict]:
        """Record how hard a cardio session felt (easy / medium / hard),
        which next week's cardio level is worked out from. None if the
        session isn't a cardio one."""
        if rating not in CARDIO_RATINGS:
            raise ValueError(f"rating must be one of {', '.join(CARDIO_RATINGS)}")
        result = (
            self.client.table("sessions")
            .update({"cardio_rating": rating})
            .eq("id", session_id)
            .eq("kind", KIND_CARDIO)
            .execute()
            .data
        )
        return result[0] if result else None

    def _reconstruct_plan(self, plan: dict, sessions: List[dict]) -> Dict[str, Any]:
        """Rebuild the full DAY_TEMPLATES-shaped schedule from a plan row and
        its sessions (each with nested session_exercises rows). A rest day
        holding a cardio session comes back as that cardio day (kind
        "cardio", with its `cardio` block); other days have kind "strength",
        or None for a rest day."""
        sessions_by_day = {s["day_number"]: s for s in sessions}

        template = DAY_TEMPLATES[plan["plan_type"]]["schedule"]
        schedule = []
        for day in template:
            session = sessions_by_day.get(day["day_number"])
            if is_cardio(session):
                day = cardio_day(day)
            elif day["is_rest_day"]:
                session = None
            entries = {"primary": [], "secondary": []}
            if session is not None:
                for row in sorted(session.get("session_exercises") or [], key=lambda r: r["id"]):
                    # Skipped by the coach for this session: not part of her
                    # workout run (the day's exercise slots skip over it).
                    if row.get("skipped"):
                        continue
                    entries[row["category"]].append(WorkoutPlanRepository._exercise_entry(row))
            entry = {
                "day_number": day["day_number"],
                "day_label": day["day_label"],
                "split_name": day["split_name"],
                "is_rest_day": day["is_rest_day"],
                "kind": None if day["is_rest_day"] else day.get("kind", KIND_STRENGTH),
                "session_id": session["id"] if session else None,
                "scheduled_date": session["scheduled_date"] if session else None,
                "primary": entries["primary"],
                "secondary": entries["secondary"],
            }
            if is_cardio(session):
                entry["cardio"] = self._cardio_block(session)
            schedule.append(entry)

        return {
            "plan_type": plan["plan_type"],
            "plan_selection_reason": plan["plan_selection_reason"],
            "medical_clearance_warning": plan["medical_clearance_warning"],
            "coach_notes": plan["coach_notes"],
            "safety_summary": plan["safety_summary"],
            "schedule": schedule,
        }

    def _workout_entries(self, plan: dict, sessions: List[dict]) -> List[dict]:
        """One entry per session (training day) of a plan, in date order: its
        split name from DAY_TEMPLATES ("Cardio" for a cardio session), its
        kind, dates, and exercises (primary first, then secondary) with
        their set logs and RPE — or, for cardio, its `cardio` block (level,
        rating, timings and the circuit). Feeds the dashboard's workout
        panels and detail screen."""
        names = {day["day_number"]: day["split_name"] for day in DAY_TEMPLATES[plan["plan_type"]]["schedule"]}
        entries = []
        for session in sorted(sessions, key=lambda s: (s["scheduled_date"], s["day_number"])):
            rows = sorted(
                session.get("session_exercises") or [],
                key=lambda r: (r["category"] != "primary", r["id"]),
            )
            cardio = is_cardio(session)
            entries.append({
                "session_id": session["id"],
                "plan_id": plan["id"],
                "day_number": session["day_number"],
                "kind": KIND_CARDIO if cardio else KIND_STRENGTH,
                "name": CARDIO_SPLIT_NAME if cardio else names.get(session["day_number"]),
                "scheduled_date": session["scheduled_date"],
                "started_at": session.get("started_at"),
                "completed_at": session.get("completed_at"),
                "is_period": bool(session.get("is_period")),
                "has_feedback": bool(session.get("feedback_audio_path")),
                "exercises": [WorkoutPlanRepository._exercise_entry(row) for row in rows],
                **({"cardio": self._cardio_block(session)} if cardio else {}),
            })
        return entries

    # ---------- admin monitor (read-only) ----------

    def list_user_profiles(self) -> List[dict]:
        return (
            self.client.table("user_profiles")
            .select("user_id, name, gender, updated_at")
            .order("name")
            .execute()
            .data
        )

    def get_user_profile_row(self, user_id: str) -> Optional[dict]:
        rows = (
            self.client.table("user_profiles")
            .select("user_id, name, gender, profile")
            .eq("user_id", user_id)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def list_joint_pain(self, user_id: str) -> List[dict]:
        rows = (
            self.client.table("user_joint_pain")
            .select("pain_level, joints(name)")
            .eq("user_id", user_id)
            .execute()
            .data
        )
        return [
            {"joint": row["joints"]["name"], "pain_level": row["pain_level"]}
            for row in rows
            if row.get("joints")
        ]

    def list_period_days(self, user_id: str) -> List[str]:
        rows = (
            self.client.table("user_period_logs")
            .select("logged_on")
            .eq("user_id", user_id)
            .order("logged_on", desc=True)
            .execute()
            .data
        )
        return [row["logged_on"] for row in rows]

    def get_session_exercise_for_edit(self, session_exercise_id: int) -> Optional[dict]:
        """One session_exercises row with its logged set numbers and its
        session (dates) and plan (owner, closed?) nested — what the coach's
        prescription edit checks before changing anything."""
        rows = (
            self.client.table("session_exercises")
            .select(
                "id, exercise_id, sets, reps, skipped, session_exercise_set_logs(set_number), "
                "sessions(id, scheduled_date, completed_at, plans(user_id, completed))"
            )
            .eq("id", session_exercise_id)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def get_current_plan_notes(self, user_id: str) -> Optional[dict]:
        """{"id", "coach_notes"} of the user's unfinished plan, or None.
        Unlike get_unfinished_plan this never closes or progresses it."""
        rows = (
            self.client.table("plans")
            .select("id, coach_notes")
            .eq("user_id", user_id)
            .eq("completed", False)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def update_coach_notes(self, plan_id: int, coach_notes: Optional[str]) -> None:
        """Set a plan's coach notes. Progression copies them into each next
        plan, so they carry forward from here."""
        self.client.table("plans").update({"coach_notes": coach_notes}).eq("id", plan_id).execute()

    def update_session_exercise_prescription(
        self,
        session_exercise_id: int,
        sets: int,
        reps: str,
        note: Any = _KEEP,
        exercise: Optional[dict] = None,
    ) -> None:
        """Set an exercise slot's prescribed sets and per-set target(s), its
        coach note when one is given (None clears it), and — when `exercise`
        (a library row) is given — swap the slot to that exercise, taking
        its rep range."""
        values: Dict[str, Any] = {"sets": sets, "reps": reps}
        if note is not _KEEP:
            values["note"] = note
        if exercise is not None:
            values["exercise_id"] = exercise["id"]
            values["rep_range"] = _rep_range(exercise)
        (
            self.client.table("session_exercises")
            .update(values)
            .eq("id", session_exercise_id)
            .execute()
        )

    def set_session_exercise_skipped(
        self, session_exercise_id: int, skipped: bool, reason: Optional[str] = None
    ) -> None:
        """Skip an exercise slot for its session only (the coach accepting an
        AI Coach suggestion), or restore it. Progression carries a skipped
        exercise into next week unchanged, as it does a missed one."""
        (
            self.client.table("session_exercises")
            .update({"skipped": skipped, "skip_reason": reason if skipped else None})
            .eq("id", session_exercise_id)
            .execute()
        )

    def count_completed_sessions(self, user_id: str) -> int:
        """How many workouts the user has finished, across all of their plans
        (period sessions included, missed ones not). Drives the dashboard's
        plant points."""
        plans = self.client.table("plans").select("id").eq("user_id", user_id).execute().data
        if not plans:
            return 0
        sessions = (
            self.client.table("sessions")
            .select("completed_at")
            .in_("plan_id", [plan["id"] for plan in plans])
            .execute()
            .data
        )
        return sum(1 for session in sessions if session.get("completed_at"))

    def get_user_workout_history(self, user_id: str) -> Dict[str, List[dict]]:
        """Every workout across all of the user's plans, split into
        {"scheduled": soonest first, "past": newest first}, each with its
        status/date (workout_status), period flag, whether she recorded voice
        feedback, the AI analysis text and voice-note URL, and how long it
        took. Read-only — unlike get_unfinished_plan it never closes or
        progresses a plan."""
        plans = self.client.table("plans").select("*").eq("user_id", user_id).execute().data
        if not plans:
            return {"scheduled": [], "past": []}
        sessions = (
            self.client.table("sessions")
            .select(f"{PLAN_SESSIONS_SELECT}, session_analysis(analysis, audio_url)")
            .in_("plan_id", [plan["id"] for plan in plans])
            .execute()
            .data
        )
        sessions_by_plan: Dict[int, List[dict]] = defaultdict(list)
        for session in sessions:
            sessions_by_plan[session["plan_id"]].append(session)

        today = app_today()
        entries = []
        for plan in plans:
            plan_sessions = sessions_by_plan[plan["id"]]
            by_id = {session["id"]: session for session in plan_sessions}
            for workout in self._workout_entries(plan, plan_sessions):
                session = by_id[workout["session_id"]]
                status, shown = workout_status(workout, today, plan_closed=bool(plan.get("completed")))
                # One row per session (unique), returned as an object or a
                # one-item list depending on how PostgREST reads the FK.
                analysis = session.get("session_analysis") or {}
                if isinstance(analysis, list):
                    analysis = analysis[0] if analysis else {}
                entries.append({
                    **workout,
                    "status": status,
                    "date": shown,
                    "duration_seconds": workout_duration_seconds(workout),
                    "analysis": analysis.get("analysis"),
                    "analysis_audio_url": analysis.get("audio_url"),
                })

        scheduled = sorted(
            (e for e in entries if e["status"] == "scheduled"),
            key=lambda e: (e["scheduled_date"], e["day_number"]),
        )
        past = sorted(
            (e for e in entries if e["status"] != "scheduled"),
            key=lambda e: (e["date"], e.get("completed_at") or ""),
            reverse=True,
        )
        return {"scheduled": scheduled, "past": past}

    @staticmethod
    def _exercise_entry(row: dict) -> Dict[str, Any]:
        exercise = WorkoutRepository._normalize_exercise(row["exercises"])
        return {
            "id": row["id"],
            "category": row.get("category"),
            "slot": row.get("slot_label"),
            "exercise_id": exercise["id"],
            "name": exercise["name"],
            "movement_type": exercise["movement_type"],
            # _normalize_exercise coerces SQL NULL to "" for CSV-repository
            # interchangeability; undo that here so a reconstructed plan's
            # orientation matches the null the workout agent originally emits.
            "orientation": exercise["orientation"] or None,
            "dominant": exercise["dominant"],
            # A hold measured in seconds: `reps` and set logs are seconds.
            "is_time_based": exercise["is_time_based"],
            "sets": row.get("sets"),
            "reps": row.get("reps"),
            "rep_range": row.get("rep_range"),
            "equipment": exercise["equipment"],
            "note": row.get("note"),
            # Same NULL-coercion undo as orientation above.
            "video_url": exercise["video_url"] or None,
            "set_logs": sorted(
                (row.get("session_exercise_set_logs") or []),
                key=lambda log: log["set_number"],
            ),
            "rpe": ((row.get("session_exercise_rpe") or {}).get("rpe")) or 8,
            # `rpe` above defaults to 8 (Medium); this says whether it was
            # actually rated.
            "rpe_logged": (row.get("session_exercise_rpe") or {}).get("rpe") is not None,
            # A voice note recorded on the exercise's feedback screen.
            "has_feedback": bool(row.get("feedback_audio_path")),
            # Skipped by the coach for this session (the AI Coach's
            # suggestions): hidden from her workout run.
            "skipped": bool(row.get("skipped")),
            "skip_reason": row.get("skip_reason"),
        }
