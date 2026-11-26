"""Supabase reads and writes for the client summary: the data it summarizes
(no diet tables) and its versions (`client_summaries` rows, each pointing at
a TXT file in the private `client-summaries` bucket).

Built on an existing Supabase client (the backend's WorkoutPlanRepository
one), so it never opens a connection of its own.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from storage3.types import FileOptions
from supabase import Client

SUMMARY_BUCKET = "client-summaries"


def summary_path(user_id: str, version: int) -> str:
    return f"{user_id}/v{version}.txt"


class ClientSummaryRepository:
    def __init__(self, client: Client):
        self.client = client

    # ---------- what it summarizes ----------

    def get_profile_row(self, user_id: str) -> Optional[Dict[str, Any]]:
        rows = (
            self.client.table("user_profiles")
            .select("user_id, name, gender, profile")
            .eq("user_id", user_id)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def get_joint_pain(self, user_id: str) -> List[Dict[str, Any]]:
        rows = (
            self.client.table("user_joint_pain")
            .select("pain_level, updated_at, joints(name)")
            .eq("user_id", user_id)
            .execute()
            .data
        )
        return [
            {"joint": row["joints"]["name"], "pain_level": row["pain_level"], "updated_at": row.get("updated_at")}
            for row in rows
            if row.get("joints")
        ]

    def get_plans(self, user_id: str) -> List[Dict[str, Any]]:
        return (
            self.client.table("plans")
            .select("id, created_at, completed, completed_at")
            .eq("user_id", user_id)
            .order("created_at")
            .execute()
            .data
        )

    def get_question_rounds(self, user_id: str) -> List[Dict[str, Any]]:
        """Every round of questions, with when each reply arrived and the
        session it was about. Small (a few rounds a week), so all are read
        and the window is applied in render.qa_lines."""
        return (
            self.client.table("session_clarifications")
            .select(
                "session_id, round, questions, answers, status, asked_at, "
                "clarification_replies(id, created_at), sessions(scheduled_date, completed_at, kind)"
            )
            .eq("user_id", user_id)
            .order("asked_at")
            .execute()
            .data
        )

    def get_exercise_names(self, session_exercise_ids: List[int]) -> Dict[int, str]:
        if not session_exercise_ids:
            return {}
        rows = (
            self.client.table("session_exercises")
            .select("id, exercises(name)")
            .in_("id", sorted(set(session_exercise_ids)))
            .execute()
            .data
        )
        return {row["id"]: (row.get("exercises") or {}).get("name") for row in rows}

    def get_comments(self, user_id: str, since: Optional[datetime], until: datetime) -> List[Dict[str, Any]]:
        query = (
            self.client.table("workout_comments")
            .select("comment, source, urgent, created_at, exercises(name)")
            .eq("user_id", user_id)
            .lte("created_at", until.isoformat())
        )
        if since is not None:
            query = query.gt("created_at", since.isoformat())
        return query.order("created_at").execute().data

    def get_period_logs(self, user_id: str, since: Optional[datetime], until: datetime) -> List[Dict[str, Any]]:
        query = (
            self.client.table("user_period_logs")
            .select("logged_on, created_at")
            .eq("user_id", user_id)
            .lte("created_at", until.isoformat())
        )
        if since is not None:
            query = query.gt("created_at", since.isoformat())
        return query.order("logged_on").execute().data

    # ---------- versions ----------

    def get_latest(self, user_id: str) -> Optional[Dict[str, Any]]:
        rows = (
            self.client.table("client_summaries")
            .select("*")
            .eq("user_id", user_id)
            .order("version", desc=True)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def read_text(self, storage_path: str) -> str:
        return self.client.storage.from_(SUMMARY_BUCKET).download(storage_path).decode("utf-8")

    def save(self, row: Dict[str, Any], text: str) -> Dict[str, Any]:
        """Upload the TXT file, then record the version. Files are never
        overwritten (upsert off): of two racing clicks for the same version,
        the second upload fails, and the (user_id, version) unique key
        backs that up, so a version's file always matches its row."""
        path = summary_path(row["user_id"], row["version"])
        self.client.storage.from_(SUMMARY_BUCKET).upload(
            path=path,
            file=text.encode("utf-8"),
            file_options=FileOptions(**{"content-type": "text/plain"}, upsert="false"),
        )
        return self.client.table("client_summaries").insert({**row, "storage_path": path}).execute().data[0]
