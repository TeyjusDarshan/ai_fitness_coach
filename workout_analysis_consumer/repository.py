import os
from typing import Any, Dict, List, Optional

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


def _shape_exercise_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Shared shaping for session_exercises rows joined via
    SESSION_DAY_EXERCISE_JOIN, used for both the current day and the
    matching day from a parent session.
    """
    return [
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
        for row in rows
    ]


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
            .select("id, user_id, plan_type, parent_session_id")
            .eq("id", session_id)
            .execute()
            .data
        )
        if not sessions:
            return None
        user_id = sessions[0]["user_id"]
        parent_session_id = sessions[0].get("parent_session_id")

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

        context = {
            "session_id": session_id,
            "day_number": day_number,
            "user_id": user_id,
            "plan_type": sessions[0]["plan_type"],
            "user_profile": profile,
            "joint_pain": [
                {"joint": row["joints"]["name"], "pain_level": row["pain_level"]}
                for row in joint_pain_rows
                if row.get("joints")
            ],
            "exercises": _shape_exercise_rows(exercise_rows),
        }

        if parent_session_id is not None:
            context["previous_session"] = self._fetch_parent_session_context(
                parent_session_id, day_number
            )

        return context

    def _fetch_parent_session_context(self, parent_session_id: int, day_number: int) -> Dict[str, Any]:
        """The parent session's data for the same day_number as the current
        analysis, so the LLM can compare like for like (same split day).
        """
        day_log_rows = (
            self.client.table("session_day_logs")
            .select("day_number, started_at, completed_at")
            .eq("session_id", parent_session_id)
            .eq("day_number", day_number)
            .execute()
            .data
        )

        exercise_rows = (
            self.client.table("session_exercises")
            .select(SESSION_DAY_EXERCISE_JOIN)
            .eq("session_id", parent_session_id)
            .eq("day_number", day_number)
            .execute()
            .data
        )

        return {
            "session_id": parent_session_id,
            "day_log": day_log_rows[0] if day_log_rows else None,
            "exercises": _shape_exercise_rows(exercise_rows),
        }

    def save_analysis(
        self,
        session_id: int,
        day_number: int,
        analysis: str,
        audio_url: Optional[str] = None,
    ) -> dict:
        """Upsert keyed by (session_id, day_number), so redelivering an
        already-processed message overwrites rather than duplicates.

        audio_url is omitted from the payload (rather than sent as None) when
        not given, so a redelivery whose voice-note generation fails doesn't
        null out audio_url from an earlier successful attempt.
        """
        row = {"session_id": session_id, "day_number": day_number, "analysis": analysis}
        if audio_url is not None:
            row["audio_url"] = audio_url
        result = (
            self.client.table("session_day_analysis")
            .upsert(row, on_conflict="session_id,day_number")
            .execute()
            .data
        )
        return result[0]
