import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

# session_exercises for one (session_id, day_number), joined with the
# exercise's name/movement type, its per-set completion logs, and its RPE.
SESSION_DAY_EXERCISE_JOIN = (
    "id, category, slot_label, sets, reps, rep_range, note, "
    "exercises(name, movement_types(name)), "
    "session_exercise_set_logs(set_number, completed_reps), "
    "session_exercise_rpe(rpe)"
)

# The app's RPE input only ever logs one of 3 values, matching
# backend/repository/workout_plan_repository.py's Easy/Medium/Hard = 6/8/10
# (PROGRESSION_TARGET_RPE=8 is the intended/ideal effort). Computed here
# rather than left for the LLM to infer, since a generic RPE scale would
# read 8 as already hard rather than as this app's target.
def _effort_flag(rpe):
    if rpe == 6:
        return "too_easy"
    if rpe == 10:
        return "too_difficult"
    return None


class AnalysisRepository:
    """Reads the Supabase data needed to summarize one workout day, and
    persists the generated summary to session_day_analysis.
    """

    def __init__(self, client: Optional[Client] = None):
        if client is not None:
            self.client = client
        else:
            url = os.environ["SUPABASE_URL"]
            key = os.environ["SUPABASE_KEY"]
            self.client = create_client(url, key)

    def fetch_context(self, session_id: int, day_number: int) -> Optional[Dict[str, Any]]:
        """Gather everything needed to summarize this session/day: the
        prescribed exercises with their set logs and RPE, the client's
        profile, and any joint pain they've reported. Returns None if the
        session doesn't exist.
        """
        sessions = (
            self.client.table("sessions")
            .select("id, user_id, plan_type")
            .eq("id", session_id)
            .execute()
            .data
        )
        if not sessions:
            return None
        user_id = sessions[0]["user_id"]

        exercise_rows = (
            self.client.table("session_exercises")
            .select(SESSION_DAY_EXERCISE_JOIN)
            .eq("session_id", session_id)
            .eq("day_number", day_number)
            .execute()
            .data
        )

        profile_rows = (
            self.client.table("user_profiles")
            .select("profile")
            .eq("user_id", user_id)
            .execute()
            .data
        )
        profile = profile_rows[0]["profile"] if profile_rows else None

        joint_pain_rows = (
            self.client.table("user_joint_pain")
            .select("pain_level, joints(name)")
            .eq("user_id", user_id)
            .execute()
            .data
        )

        return {
            "session_id": session_id,
            "day_number": day_number,
            "plan_type": sessions[0]["plan_type"],
            "user_profile": profile,
            "joint_pain": [
                {"joint": row["joints"]["name"], "pain_level": row["pain_level"]}
                for row in joint_pain_rows
                if row.get("joints")
            ],
            "exercises": [
                {
                    "name": row["exercises"]["name"],
                    "movement_type": (row["exercises"].get("movement_types") or {}).get("name"),
                    "slot": row.get("slot_label"),
                    "prescribed_sets": row.get("sets"),
                    "prescribed_reps": row.get("reps"),
                    "rep_range": row.get("rep_range"),
                    "set_logs": sorted(
                        (row.get("session_exercise_set_logs") or []),
                        key=lambda log: log["set_number"],
                    ),
                    "rpe": (row.get("session_exercise_rpe") or {}).get("rpe"),
                    "effort_flag": _effort_flag((row.get("session_exercise_rpe") or {}).get("rpe")),
                }
                for row in exercise_rows
            ],
        }

    def save_analysis(self, session_id: int, day_number: int, analysis: str) -> dict:
        """Upsert keyed by (session_id, day_number), so redelivering an
        already-processed message overwrites rather than duplicates.
        """
        row = {"session_id": session_id, "day_number": day_number, "analysis": analysis}
        result = (
            self.client.table("session_day_analysis")
            .upsert(row, on_conflict="session_id,day_number")
            .execute()
            .data
        )
        return result[0]
