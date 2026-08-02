import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from supabase import create_client, Client

from agents.prompts_v1 import DAY_TEMPLATES
from backend.repository.workout_repository import WorkoutRepository

load_dotenv()

SESSION_EXERCISE_JOIN = (
    "*, exercises(*, movement_types(name), equipment(name), exercise_loaded_joints(joints(name)))"
)


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

    def create_session(self, user_id: str, plan: Dict[str, Any]) -> dict:
        session_row = {
            "user_id": user_id,
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
                        "completed_sets": [False] * sets if sets else [],
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
        return result[0] if result else None

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

    def set_completed(
        self, session_id: int, session_exercise_id: int, set_index: int, completed: bool
    ) -> Optional[List[bool]]:
        """Flip one entry of a session_exercises row's completed_sets.

        Ownership/bounds are validated with a read first (their outcome never
        changes after row creation, so no race there); the actual flip runs
        through the set_session_exercise_set() Postgres function, which does
        the jsonb_set update in a single atomic statement. Two rapid toggles
        on different indices of the same row (e.g. checking two sets back to
        back) would otherwise race under a client-side read-modify-write and
        silently lose one of the updates.

        Returns the updated array, or None if session_exercise_id doesn't
        belong to session_id or set_index is out of range.
        """
        rows = (
            self.client.table("session_exercises")
            .select("completed_sets")
            .eq("id", session_exercise_id)
            .eq("session_id", session_id)
            .execute()
            .data
        )
        if not rows:
            return None

        current_length = len(rows[0].get("completed_sets") or [])
        if set_index < 0 or set_index >= current_length:
            return None

        result = self.client.rpc(
            "set_session_exercise_set",
            {
                "p_session_exercise_id": session_exercise_id,
                "p_set_index": set_index,
                "p_completed": completed,
            },
        ).execute()
        return result.data

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
            .select("completed_sets")
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
            completed_sets = row.get("completed_sets") or []
            total_sets += len(completed_sets)
            done = sum(1 for s in completed_sets if s)
            sets_completed += done
            if completed_sets and done == len(completed_sets):
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
                "completed_sets": row.get("completed_sets") or [],
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
