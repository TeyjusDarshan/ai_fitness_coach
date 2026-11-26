"""Supabase reads and writes for the AI Coach agent: everything it needs to
know about one scheduled session and its client, and the suggestion runs it
stores (coach_suggestion_runs / exercise_suggestions).

Built on an existing Supabase client (the backend's WorkoutPlanRepository
one), so it never opens a connection of its own.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from supabase import Client

# How many earlier same-day sessions ("the last two weeks of this day") it reads.
SAME_DAY_WEEKS = 2
# Plans walked up parent_plan_id looking for those same-day sessions.
MAX_PLAN_HOPS = 6

EXERCISE_FIELDS = (
    "id, name, min_reps, max_reps, is_time_based, avoid_if, orientation, dominant, "
    "movement_types(name), equipment(name), exercise_loaded_joints(joint_load, joints(name))"
)
SESSION_EXERCISE_SELECT = (
    f"id, exercise_id, category, slot_label, sets, reps, rep_range, note, skipped, skip_reason, "
    f"exercises({EXERCISE_FIELDS}), "
    "session_exercise_set_logs(set_number, completed_reps), session_exercise_rpe(rpe)"
)
HISTORY_EXERCISE_SELECT = (
    "id, exercise_id, sets, reps, skipped, exercises(name, is_time_based), "
    "session_exercise_set_logs(set_number, completed_reps), session_exercise_rpe(rpe)"
)


class CoachAgentRepository:
    def __init__(self, client: Client):
        self.client = client

    # ---------- reads ----------

    def get_session(self, session_id: int) -> Optional[Dict[str, Any]]:
        """The session with its plan and its exercises (library details,
        loaded joints with load, set logs, RPE) nested."""
        rows = (
            self.client.table("sessions")
            .select(
                "id, plan_id, day_number, scheduled_date, started_at, completed_at, is_period, kind, "
                "plans(id, user_id, plan_type, parent_plan_id, completed, coach_notes, safety_summary), "
                f"session_exercises({SESSION_EXERCISE_SELECT})"
            )
            .eq("id", session_id)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def get_exercise_edges(self, exercise_ids: List[int]) -> List[Dict[str, Any]]:
        """Progression/regression edges out of these exercises, each with the
        target exercise's library details."""
        if not exercise_ids:
            return []
        return (
            self.client.table("exercise_relationships")
            .select(
                "from_exercise_id, type, reason, "
                f"exercises!exercise_relationships_to_exercise_id_fkey({EXERCISE_FIELDS})"
            )
            .in_("from_exercise_id", sorted(set(exercise_ids)))
            .execute()
            .data
        )

    def get_same_day_history(
        self, parent_plan_id: Optional[int], day_number: int, weeks: int = SAME_DAY_WEEKS
    ) -> List[Dict[str, Any]]:
        """The sessions for the same day_number in the previous `weeks`
        plans (walking up parent_plan_id), newest first, whatever happened
        to them (completed, missed, on her period) — with their exercises."""
        sessions = []
        plan_id = parent_plan_id
        for _ in range(MAX_PLAN_HOPS):
            if plan_id is None or len(sessions) == weeks:
                break
            rows = (
                self.client.table("sessions")
                .select(
                    "id, day_number, scheduled_date, started_at, completed_at, is_period, kind, "
                    f"plans(parent_plan_id), session_exercises({HISTORY_EXERCISE_SELECT})"
                )
                .eq("plan_id", plan_id)
                .eq("day_number", day_number)
                .execute()
                .data
            )
            plan_parent = None
            if rows:
                sessions.append(rows[0])
                plan_parent = (rows[0].get("plans") or {}).get("parent_plan_id")
            else:
                plan_rows = (
                    self.client.table("plans").select("parent_plan_id").eq("id", plan_id).execute().data
                )
                plan_parent = plan_rows[0]["parent_plan_id"] if plan_rows else None
            plan_id = plan_parent
        return sessions

    # ---------- suggestion runs ----------

    def save_run(
        self, session_id: int, user_id: str, overview: str, model: str, suggestions: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Store a run and its suggestions; the session's earlier pending
        suggestions become superseded. Returns the run with its rows."""
        earlier_runs = (
            self.client.table("coach_suggestion_runs").select("id").eq("session_id", session_id).execute().data
        )
        if earlier_runs:
            (
                self.client.table("exercise_suggestions")
                .update({"status": "superseded"})
                .in_("run_id", [run["id"] for run in earlier_runs])
                .eq("status", "pending")
                .execute()
            )
        run = (
            self.client.table("coach_suggestion_runs")
            .insert({"session_id": session_id, "user_id": user_id, "overview": overview, "model": model})
            .execute()
            .data[0]
        )
        rows = []
        if suggestions:
            rows = (
                self.client.table("exercise_suggestions")
                .insert([{**suggestion, "run_id": run["id"]} for suggestion in suggestions])
                .execute()
                .data
            )
        return {**run, "exercise_suggestions": rows}

    def get_latest_run(self, session_id: int) -> Optional[Dict[str, Any]]:
        rows = (
            self.client.table("coach_suggestion_runs")
            .select("*, exercise_suggestions(*)")
            .eq("session_id", session_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def get_suggestion(self, suggestion_id: int) -> Optional[Dict[str, Any]]:
        rows = (
            self.client.table("exercise_suggestions")
            .select("*, coach_suggestion_runs(session_id, user_id)")
            .eq("id", suggestion_id)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def set_suggestion_status(self, suggestion_id: int, status: str) -> None:
        (
            self.client.table("exercise_suggestions")
            .update({"status": status, "decided_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", suggestion_id)
            .execute()
        )

    def get_exercises(self, exercise_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """id -> {id, name, min_reps, max_reps, is_time_based} for display."""
        if not exercise_ids:
            return {}
        rows = (
            self.client.table("exercises")
            .select("id, name, min_reps, max_reps, is_time_based")
            .in_("id", sorted(set(exercise_ids)))
            .execute()
            .data
        )
        return {row["id"]: row for row in rows}
