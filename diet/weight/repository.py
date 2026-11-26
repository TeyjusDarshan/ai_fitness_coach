"""Supabase reads and writes for weight tracking: `weight_logs`,
`weight_weeks`, `nutrition_target_changes`, `weight_nudges`, and the bits of
`user_profiles` / `user_period_logs` / `whatsapp_reply_windows` the rules
need (diet/weight/schema.sql)."""
import os
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

PROFILE_COLUMNS = ("user_id, name, gender, whatsapp_number, timezone, diet_enabled, diet_setup, "
                   "nutrition_targets, weight_goal, weight_goal_kg")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_duplicate(error: Exception) -> bool:
    return "duplicate key" in str(error) or "23505" in str(error)


class WeightRepository:
    def __init__(self, client: Optional[Client] = None):
        self.client = client or create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

    # --- her profile -----------------------------------------------------

    def get_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        rows = self.client.table("user_profiles").select(PROFILE_COLUMNS).eq("user_id", user_id).limit(1).execute().data
        return rows[0] if rows else None

    def list_tracked_profiles(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Every client weight tracking applies to: diet tracking on and the
        diet setup done (optionally just one)."""
        query = (self.client.table("user_profiles").select(PROFILE_COLUMNS)
                 .eq("diet_enabled", True).not_.is_("diet_setup", "null"))
        if user_id:
            query = query.eq("user_id", user_id)
        return query.order("user_id").execute().data

    def set_weight_goal(self, user_id: str, goal: str, goal_kg: Optional[float]) -> None:
        self.client.table("user_profiles").update({"weight_goal": goal, "weight_goal_kg": goal_kg}).eq(
            "user_id", user_id).execute()

    def set_targets(self, user_id: str, targets: Dict[str, Any]) -> None:
        self.client.table("user_profiles").update({"nutrition_targets": targets}).eq("user_id", user_id).execute()

    # --- readings --------------------------------------------------------

    def list_readings(self, user_id: str, start: date, end: date) -> List[Dict[str, Any]]:
        """Her readings for start..end (inclusive), oldest first."""
        return (self.client.table("weight_logs").select("*").eq("user_id", user_id)
                .gte("measured_on", start.isoformat()).lte("measured_on", end.isoformat())
                .order("measured_on").execute().data)

    def first_reading(self, user_id: str) -> Optional[Dict[str, Any]]:
        rows = (self.client.table("weight_logs").select("*").eq("user_id", user_id)
                .order("measured_on").limit(1).execute().data)
        return rows[0] if rows else None

    def has_reading(self, user_id: str, day: date) -> bool:
        return bool(self.client.table("weight_logs").select("id").eq("user_id", user_id)
                    .eq("measured_on", day.isoformat()).limit(1).execute().data)

    def upsert_reading(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Her reading for the day; a later one the same day replaces it."""
        return self.client.table("weight_logs").upsert(
            {**row, "updated_at": _now()}, on_conflict="user_id,measured_on"
        ).execute().data[0]

    def add_setup_reading(self, user_id: str, day: date, weight_kg: float) -> None:
        """Her diet-setup weight as her first reading (kept if she already
        sent one that day)."""
        self.client.table("weight_logs").upsert(
            {"user_id": user_id, "measured_on": day.isoformat(), "weight_kg": round(weight_kg, 1), "source": "setup"},
            on_conflict="user_id,measured_on", ignore_duplicates=True,
        ).execute()

    # --- weeks -----------------------------------------------------------

    def list_weeks(self, user_id: str, limit: int = 104) -> List[Dict[str, Any]]:
        """Her closed weeks, newest first."""
        return (self.client.table("weight_weeks").select("*").eq("user_id", user_id)
                .order("week_start", desc=True).limit(limit).execute().data)

    def get_week(self, user_id: str, week_start: date) -> Optional[Dict[str, Any]]:
        rows = (self.client.table("weight_weeks").select("*").eq("user_id", user_id)
                .eq("week_start", week_start.isoformat()).limit(1).execute().data)
        return rows[0] if rows else None

    def create_week(self, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """None when that week was already closed (another run got there first)."""
        try:
            return self.client.table("weight_weeks").insert(row).execute().data[0]
        except Exception as error:
            if _is_duplicate(error):
                return None
            raise

    def update_week(self, week_id: int, fields: Dict[str, Any]) -> None:
        self.client.table("weight_weeks").update(fields).eq("id", week_id).execute()

    # --- calorie changes -------------------------------------------------

    def list_changes(self, user_id: str) -> List[Dict[str, Any]]:
        """Every change to her targets, oldest first."""
        return (self.client.table("nutrition_target_changes").select("*").eq("user_id", user_id)
                .order("created_at").execute().data)

    def get_change(self, change_id: int) -> Optional[Dict[str, Any]]:
        rows = self.client.table("nutrition_target_changes").select("*").eq("id", change_id).limit(1).execute().data
        return rows[0] if rows else None

    def create_change(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return self.client.table("nutrition_target_changes").insert(row).execute().data[0]

    def decide_change(self, change_id: int, status: str) -> bool:
        """Accept or reject a pending change; False if it isn't pending any
        more (decided elsewhere or superseded)."""
        rows = (self.client.table("nutrition_target_changes")
                .update({"status": status, "decided_at": _now()})
                .eq("id", change_id).eq("status", "pending").execute().data)
        return bool(rows)

    def update_change(self, change_id: int, fields: Dict[str, Any]) -> None:
        self.client.table("nutrition_target_changes").update(fields).eq("id", change_id).execute()

    def supersede_pending(self, user_id: str) -> None:
        (self.client.table("nutrition_target_changes").update({"status": "superseded", "decided_at": _now()})
         .eq("user_id", user_id).eq("status", "pending").execute())

    # --- period days -----------------------------------------------------

    def period_days(self, user_id: str, start: date, end: date) -> List[str]:
        rows = (self.client.table("user_period_logs").select("logged_on").eq("user_id", user_id)
                .gte("logged_on", start.isoformat()).lte("logged_on", end.isoformat()).execute().data)
        return [row["logged_on"] for row in rows]

    # --- nudges ----------------------------------------------------------

    def get_nudge(self, user_id: str, day: date, kind: str) -> Optional[Dict[str, Any]]:
        rows = (self.client.table("weight_nudges").select("*").eq("user_id", user_id)
                .eq("nudge_date", day.isoformat()).eq("kind", kind).limit(1).execute().data)
        return rows[0] if rows else None

    def intro_sent(self, user_id: str) -> bool:
        return bool(self.client.table("weight_nudges").select("id").eq("user_id", user_id)
                    .eq("kind", "intro").eq("status", "sent").limit(1).execute().data)

    def create_nudge(self, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            return self.client.table("weight_nudges").insert(row).execute().data[0]
        except Exception as error:
            if _is_duplicate(error):
                return None
            raise

    def update_nudge(self, nudge_id: int, fields: Dict[str, Any]) -> None:
        self.client.table("weight_nudges").update(fields).eq("id", nudge_id).execute()

    def recent_nudge(self, user_id: str, since: datetime) -> Optional[Dict[str, Any]]:
        """Her latest weigh-in message actually sent since `since`."""
        rows = (self.client.table("weight_nudges").select("kind, sent_at").eq("user_id", user_id)
                .eq("status", "sent").gte("sent_at", since.isoformat())
                .order("sent_at", desc=True).limit(1).execute().data)
        return rows[0] if rows else None

    # --- WhatsApp --------------------------------------------------------

    def reply_window_open(self, phone_number: Optional[str]) -> bool:
        if not phone_number:
            return False
        rows = (self.client.table("whatsapp_reply_windows").select("window_open")
                .eq("phone_number", phone_number).limit(1).execute().data)
        return bool(rows) and rows[0].get("window_open") is True
