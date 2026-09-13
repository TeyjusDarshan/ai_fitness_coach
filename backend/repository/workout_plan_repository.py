import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from supabase import create_client, Client

from agents.prompts_v1 import DAY_TEMPLATES
from backend.repository.workout_repository import WorkoutRepository

load_dotenv()

logger = logging.getLogger(__name__)

SESSION_EXERCISE_JOIN = (
    "*, exercises(*, movement_types(name), equipment(name), exercise_loaded_joints(joints(name))), "
    "session_exercise_set_logs(set_number, completed_reps), session_exercise_rpe(rpe)"
)

# Lighter than SESSION_EXERCISE_JOIN: progression only needs exercise_id (not
# the nested exercises(...) join) since it's carried forward as-is into the
# next session's session_exercises rows, never rendered.
PROGRESSION_EXERCISE_SELECT = (
    "id, exercise_id, day_number, category, slot_label, sets, reps, rep_range, note, "
    "session_exercise_set_logs(set_number, completed_reps), session_exercise_rpe(rpe)"
)

# Autoregulated-progression constants — see _compute_progressed_reps.
PROGRESSION_TARGET_RPE = 8
PROGRESSION_FALLBACK_RPE = 10  # goal not met, or met but RPE was never logged
PROGRESSION_DIVISOR = 3
PROGRESSION_MIN_REPS = 1

# performance_factor (TARGET_RPE - actual_rpe) -> volume multiplier. Keyed by
# the 3 performance_factor values the app's RPE inputs actually produce
# (Easy/Medium/Hard = rpe 6/8/10 -> PF 2/0/-2); a reported rpe outside
# {6, 8, 10} is possible via direct API use, so _compute_progressed_reps
# snaps performance_factor to whichever of these keys it's closest to.
PROGRESSION_PF_MULTIPLIERS = {-2: 0.9, 0: 1.02, 2: 1.1}

# exercise_relationships.reason is semicolon-delimited when an edge has more
# than one reason (e.g. "Lack of form;Lack of strength") — substring match
# catches both that and the plain "Lack of strength" case.
REGRESSION_REASON_FILTER = "lack of strength"


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


def _compute_progressed_reps(
    exercise_row: Dict[str, Any], injury_multiplier: Optional[float] = None
) -> int:
    """Autoregulated next-session reps target for one session_exercises row.

    "Met" requires a logged set for every prescribed `sets` slot, each at or
    above that row's target `reps`. If met, actual_rpe is the user-reported
    session_exercise_rpe value; otherwise (goal not met, or met but no RPE
    was ever logged) it falls back to PROGRESSION_FALLBACK_RPE, same as a
    missed goal. performance_factor = TARGET_RPE - actual_rpe is mapped to a
    multiplier via PROGRESSION_PF_MULTIPLIERS and applied to last session's
    average reps per set (total_volume / PROGRESSION_DIVISOR). Floored at
    PROGRESSION_MIN_REPS so the result written to the varchar `reps` column
    is never zero, negative, or fractional.

    If injury_multiplier is given (the exercise loads a joint the user has
    reported pain in — see _injury_multiplier_for_exercise), it replaces the
    RPE-derived multiplier entirely rather than the two being combined, since
    the injury factor already encodes "back off regardless of performance."
    """
    prescribed_sets = exercise_row.get("sets") or 0
    try:
        target_reps = int(exercise_row.get("reps"))
    except (TypeError, ValueError):
        target_reps = None

    set_logs = exercise_row.get("session_exercise_set_logs") or []
    logged_by_set = {log["set_number"]: log["completed_reps"] for log in set_logs}

    if injury_multiplier is not None:
        multiplier = injury_multiplier
    else:
        met_target = (
            target_reps is not None
            and prescribed_sets > 0
            and len(logged_by_set) >= prescribed_sets
            and all(logged_by_set.get(n, 0) >= target_reps for n in range(1, prescribed_sets + 1))
        )

        if met_target:
            reported_rpe = (exercise_row.get("session_exercise_rpe") or {}).get("rpe") or None
            actual_rpe = reported_rpe if reported_rpe is not None else PROGRESSION_FALLBACK_RPE
        else:
            actual_rpe = PROGRESSION_FALLBACK_RPE

        performance_factor = PROGRESSION_TARGET_RPE - actual_rpe
        nearest_pf = min(PROGRESSION_PF_MULTIPLIERS, key=lambda pf: abs(pf - performance_factor))
        multiplier = PROGRESSION_PF_MULTIPLIERS[nearest_pf]

    total_volume = sum(logged_by_set.values())
    next_reps = multiplier * (total_volume / PROGRESSION_DIVISOR)
    return max(PROGRESSION_MIN_REPS, round(next_reps))


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

    def upsert_user_profile(self, user_id: str, profile: Dict[str, Any]) -> dict:
        row = {
            "user_id": user_id,
            "profile": profile,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
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

    def user_exists(self, user_id: str) -> bool:
        rows = (
            self.client.table("user_profiles")
            .select("user_id")
            .eq("user_id", user_id)
            .execute()
            .data
        )
        return bool(rows)

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

    def get_unfinished_session(self, user_id: str) -> Optional[dict]:
        sessions = (
            self.client.table("sessions")
            .select("*")
            .eq("user_id", user_id)
            .eq("completed", False)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        if not sessions:
            return None
        session = sessions[0]

        exercise_rows = (
            self.client.table("session_exercises")
            .select(SESSION_EXERCISE_JOIN)
            .eq("session_id", session["id"])
            .order("day_number")
            .execute()
            .data
        )
        return {
            "id": session["id"],
            "completed": session["completed"],
            "plan": self._reconstruct_plan(session, exercise_rows),
        }

    def get_last_completed_session(self, user_id: str) -> Optional[dict]:
        sessions = (
            self.client.table("sessions")
            .select("*")
            .eq("user_id", user_id)
            .eq("completed", True)
            .order("completed_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        if not sessions:
            return None
        session = sessions[0]

        exercise_rows = (
            self.client.table("session_exercises")
            .select(PROGRESSION_EXERCISE_SELECT)
            .eq("session_id", session["id"])
            .execute()
            .data
        )
        return {"session": session, "exercise_rows": exercise_rows}

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
        """id -> {min_reps, max_reps} for the given exercises, batched into one query."""
        if not exercise_ids:
            return {}
        rows = (
            self.client.table("exercises")
            .select("id, min_reps, max_reps")
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

    def create_progressed_session(
        self, user_id: str, source_session: dict, exercise_rows: List[dict]
    ) -> dict:
        """Insert the next session by carrying forward source_session's exercises,
        recalculating each row's `reps` via _compute_progressed_reps.

        Each exercise's reps target is computed by _compute_progressed_reps,
        using an injury multiplier (_injury_multiplier_for_exercise) in place
        of the RPE-based one wherever the exercise loads a joint the user has
        reported pain in (user_joint_pain), and the ordinary RPE-based
        multiplier otherwise.

        If the recalculated reps falls below the exercise's own `min_reps`
        (from `exercises`), the exercise is swapped for its "lack of
        strength" regression (`exercise_relationships`) and reps is set to
        that regression's own `min_reps`. If it exceeds `max_reps`, the
        exercise is swapped for its progression and reps is set to *that*
        exercise's `min_reps`. If no matching regression/progression edge
        exists, the exercise is kept as-is and reps is clamped to its own
        min_reps/max_reps instead. `rep_range` is refreshed to match a
        swapped-in exercise's own min-max (per the "matched catalog row's
        f'{min_reps}-{max_reps}'" convention); everything else
        (day_number/category/slot_label/sets/note) is carried over unchanged.

        This applies uniformly regardless of *why* reps dropped, so an
        injury-driven low multiplier can swap an exercise to its regression
        exactly like a poor-performance one would.
        """
        completed_at = source_session.get("completed_at")
        session_row = {
            "user_id": user_id,
            "parent_session_id": source_session.get("id"),
            "plan_type": source_session.get("plan_type"),
            "plan_selection_reason": (
                f"Progressive overload from the session completed on {completed_at}."
                if completed_at
                else "Progressive overload from the previous completed session."
            ),
            "medical_clearance_warning": source_session.get("medical_clearance_warning"),
            "coach_notes": source_session.get("coach_notes"),
            "safety_summary": source_session.get("safety_summary"),
        }
        session = self.client.table("sessions").insert(session_row).execute().data[0]

        user_joint_pain = self._fetch_user_joint_pain(user_id)
        loaded_joints_by_exercise = self._fetch_loaded_joints(
            [row["exercise_id"] for row in exercise_rows]
        )
        computed_reps = {
            row["id"]: _compute_progressed_reps(
                row,
                self._injury_multiplier_for_exercise(
                    row["exercise_id"], loaded_joints_by_exercise, user_joint_pain
                ),
            )
            for row in exercise_rows
        }
        rep_bounds = self._fetch_exercise_rep_bounds([row["exercise_id"] for row in exercise_rows])

        below_min_ids = [
            row["exercise_id"]
            for row in exercise_rows
            if row["exercise_id"] in rep_bounds
            and computed_reps[row["id"]] < rep_bounds[row["exercise_id"]]["min_reps"]
        ]
        above_max_ids = [
            row["exercise_id"]
            for row in exercise_rows
            if row["exercise_id"] in rep_bounds
            and computed_reps[row["id"]] > rep_bounds[row["exercise_id"]]["max_reps"]
        ]
        regressions = self._fetch_regressions(below_min_ids)
        progressions = self._fetch_progressions(above_max_ids)

        replacement_ids = set(regressions.values()) | set(progressions.values())
        replacement_bounds = self._fetch_exercise_rep_bounds(list(replacement_ids))

        new_exercise_rows = []
        for row in exercise_rows:
            exercise_id = row["exercise_id"]
            rep_range = row.get("rep_range")
            bounds = rep_bounds.get(exercise_id)
            next_reps = computed_reps[row["id"]]

            if bounds is not None and next_reps < bounds["min_reps"]:
                target_id = regressions.get(exercise_id)
                if target_id is not None:
                    exercise_id = target_id
                    target_bounds = replacement_bounds[target_id]
                    next_reps = target_bounds["min_reps"]
                    rep_range = f"{target_bounds['min_reps']}-{target_bounds['max_reps']}"
                else:
                    next_reps = bounds["min_reps"]
            elif bounds is not None and next_reps > bounds["max_reps"]:
                target_id = progressions.get(exercise_id)
                if target_id is not None:
                    exercise_id = target_id
                    target_bounds = replacement_bounds[target_id]
                    next_reps = target_bounds["min_reps"]
                    rep_range = f"{target_bounds['min_reps']}-{target_bounds['max_reps']}"
                else:
                    next_reps = bounds["max_reps"]

            new_exercise_rows.append({
                "session_id": session["id"],
                "exercise_id": exercise_id,
                "day_number": row["day_number"],
                "category": row["category"],
                "slot_label": row.get("slot_label"),
                "sets": row.get("sets"),
                "reps": str(next_reps),
                "rep_range": rep_range,
                "note": row.get("note"),
            })
        if new_exercise_rows:
            self.client.table("session_exercises").insert(new_exercise_rows).execute()

        return session

    def create_session(self, user_id: str, plan: Dict[str, Any]) -> dict:
        session_row = {
            "user_id": user_id,
            "parent_session_id": None,
            "plan_type": plan.get("plan_type"),
            "plan_selection_reason": plan.get("plan_selection_reason"),
            "medical_clearance_warning": plan.get("medical_clearance_warning"),
            "coach_notes": plan.get("coach_notes"),
            "safety_summary": plan.get("safety_summary"),
        }
        session = self.client.table("sessions").insert(session_row).execute().data[0]

        exercise_rows = []
        for day in plan.get("schedule", []):
            if day.get("is_rest_day"):
                continue
            for category in ("primary", "secondary"):
                for ex in day.get(category, []):
                    sets = ex.get("sets")
                    exercise_rows.append({
                        "session_id": session["id"],
                        "exercise_id": ex["exercise_id"],
                        "day_number": day["day_number"],
                        "category": category,
                        "slot_label": ex.get("slot"),
                        "sets": sets,
                        "reps": ex.get("reps"),
                        "rep_range": ex.get("rep_range"),
                        "note": ex.get("note"),
                    })
        if exercise_rows:
            self.client.table("session_exercises").insert(exercise_rows).execute()

        return session

    def mark_session_completed(self, session_id: int) -> Optional[dict]:
        result = (
            self.client.table("sessions")
            .update({"completed": True, "completed_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", session_id)
            .execute()
            .data
        )
        if not result:
            return None
        completed_session = result[0]
        self._auto_progress(completed_session)
        return completed_session

    def _auto_progress(self, completed_session: dict) -> None:
        """Generate the next week's session as soon as this one is marked
        completed, so the user always has a next plan waiting without having
        to call POST /api/users/<user_id>/progress-plan themselves.

        Best-effort: the session is already committed as completed regardless
        of whether this succeeds, so a failure here is logged and swallowed
        rather than surfaced as a failure of whatever request triggered the
        completion (day-completion or the manual admin endpoint).
        """
        try:
            exercise_rows = (
                self.client.table("session_exercises")
                .select(PROGRESSION_EXERCISE_SELECT)
                .eq("session_id", completed_session["id"])
                .execute()
                .data
            )
            if exercise_rows:
                self.create_progressed_session(
                    completed_session["user_id"], completed_session, exercise_rows
                )
        except Exception:
            logger.exception(
                "Failed to auto-generate progressed session for user_id=%s after session_id=%s completed",
                completed_session.get("user_id"),
                completed_session.get("id"),
            )

    def list_day_logs(self, session_id: int) -> Dict[int, dict]:
        rows = (
            self.client.table("session_day_logs")
            .select("day_number, started_at, completed_at")
            .eq("session_id", session_id)
            .execute()
            .data
        )
        return {row["day_number"]: row for row in rows}

    def start_day(self, session_id: int, day_number: int) -> dict:
        """Get-or-create the session_day_logs row for this (session, day).

        started_at is never overwritten once set, so re-entering a day the
        user already began doesn't reset its Total Time baseline.
        """
        existing = (
            self.client.table("session_day_logs")
            .select("*")
            .eq("session_id", session_id)
            .eq("day_number", day_number)
            .execute()
            .data
        )
        if existing:
            return existing[0]

        row = {
            "session_id": session_id,
            "day_number": day_number,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        result = (
            self.client.table("session_day_logs")
            .upsert(row, on_conflict="session_id,day_number", ignore_duplicates=True)
            .execute()
            .data
        )
        if result:
            return result[0]

        # Another request created the row between our select and upsert.
        existing = (
            self.client.table("session_day_logs")
            .select("*")
            .eq("session_id", session_id)
            .eq("day_number", day_number)
            .execute()
            .data
        )
        return existing[0]

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
        belong to session_id or set_number is out of range.
        """
        rows = (
            self.client.table("session_exercises")
            .select("sets")
            .eq("id", session_exercise_id)
            .eq("session_id", session_id)
            .execute()
            .data
        )
        if not rows:
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
        """Upsert the session_exercise_rpe row for one exercise (one RPE per exercise per session)."""
        rows = (
            self.client.table("session_exercises")
            .select("id")
            .eq("id", session_exercise_id)
            .eq("session_id", session_id)
            .execute()
            .data
        )
        if not rows:
            return None

        row = {"session_exercise_id": session_exercise_id, "rpe": rpe}
        result = (
            self.client.table("session_exercise_rpe")
            .upsert(row, on_conflict="session_exercise_id")
            .execute()
            .data
        )
        return result[0] if result else None

    def complete_day(self, session_id: int, day_number: int) -> Optional[dict]:
        sessions = self.client.table("sessions").select("*").eq("id", session_id).execute().data
        if not sessions:
            return None
        session = sessions[0]

        now = datetime.now(timezone.utc)
        day_log_rows = (
            self.client.table("session_day_logs")
            .select("*")
            .eq("session_id", session_id)
            .eq("day_number", day_number)
            .execute()
            .data
        )
        started_at = day_log_rows[0]["started_at"] if day_log_rows and day_log_rows[0]["started_at"] else None
        if not started_at:
            # Defensive: complete_day was called without a prior start_day.
            started_at = now.isoformat()

        log_row = {
            "session_id": session_id,
            "day_number": day_number,
            "started_at": started_at,
            "completed_at": now.isoformat(),
        }
        self.client.table("session_day_logs").upsert(log_row, on_conflict="session_id,day_number").execute()

        exercise_rows = (
            self.client.table("session_exercises")
            .select("sets, session_exercise_set_logs(set_number)")
            .eq("session_id", session_id)
            .eq("day_number", day_number)
            .execute()
            .data
        )
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

        plan_completed = False
        template = DAY_TEMPLATES.get(session["plan_type"], {}).get("schedule", [])
        non_rest_days = {d["day_number"] for d in template if not d["is_rest_day"]}
        if non_rest_days:
            all_logs = self.list_day_logs(session_id)
            if all(all_logs.get(d, {}).get("completed_at") for d in non_rest_days):
                self.mark_session_completed(session_id)
                plan_completed = True

        return {
            "day_number": day_number,
            "total_time_seconds": total_time_seconds,
            "exercises_completed": exercises_completed,
            "total_exercises": total_exercises,
            "sets_completed": sets_completed,
            "total_sets": total_sets,
            "plan_completed": plan_completed,
        }

    @staticmethod
    def _reconstruct_plan(session: dict, exercise_rows: List[dict]) -> Dict[str, Any]:
        by_day = defaultdict(lambda: {"primary": [], "secondary": []})
        for row in exercise_rows:
            exercise = WorkoutRepository._normalize_exercise(row["exercises"])
            entry = {
                "id": row["id"],
                "slot": row.get("slot_label"),
                "exercise_id": exercise["id"],
                "name": exercise["name"],
                "movement_type": exercise["movement_type"],
                # _normalize_exercise coerces SQL NULL to "" for CSV-repository
                # interchangeability; undo that here so a reconstructed plan's
                # orientation matches the null the workout agent originally emits.
                "orientation": exercise["orientation"] or None,
                "dominant": exercise["dominant"],
                "sets": row.get("sets"),
                "reps": row.get("reps"),
                "rep_range": row.get("rep_range"),
                "equipment": exercise["equipment"],
                "note": row.get("note"),
                "set_logs": sorted(
                    (row.get("session_exercise_set_logs") or []),
                    key=lambda log: log["set_number"],
                ),
                "rpe": ((row.get("session_exercise_rpe") or {}).get("rpe")) or 8
            }
            by_day[row["day_number"]][row["category"]].append(entry)

        template = DAY_TEMPLATES[session["plan_type"]]["schedule"]
        schedule = []
        for day in template:
            entry = {
                "day_number": day["day_number"],
                "day_label": day["day_label"],
                "split_name": day["split_name"],
                "is_rest_day": day["is_rest_day"],
                "primary": [] if day["is_rest_day"] else by_day[day["day_number"]]["primary"],
                "secondary": [] if day["is_rest_day"] else by_day[day["day_number"]]["secondary"],
            }
            schedule.append(entry)

        return {
            "plan_type": session["plan_type"],
            "plan_selection_reason": session["plan_selection_reason"],
            "medical_clearance_warning": session["medical_clearance_warning"],
            "coach_notes": session["coach_notes"],
            "safety_summary": session["safety_summary"],
            "schedule": schedule,
        }
