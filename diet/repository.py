"""Supabase reads and writes for diet tracking: her `meal_logs` ->
`meal_log_items` -> `meal_log_item_ingredients`, and the read-only
`ingredient_nutrition_reference` they point at."""
import os
import time
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from supabase import Client, create_client

from diet.nutrition import NUTRIENTS

load_dotenv()

REFERENCE_TABLE = "ingredient_nutrition_reference"
REFERENCE_COLUMNS = "id, name, category, " + ", ".join(NUTRIENTS)
ITEM_SELECT = f"*, meal_log_item_ingredients(*, {REFERENCE_TABLE}({REFERENCE_COLUMNS}))"
LOG_SELECT = f"*, meal_log_items({ITEM_SELECT})"
# The reference table changes rarely (by hand in the dashboard).
REFERENCE_CACHE_SECONDS = 300


class DietRepository:
    def __init__(self, client: Optional[Client] = None):
        self.client = client or create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
        self._reference_cache: Optional[Tuple[float, List[Dict[str, Any]]]] = None

    # --- the reference table ---------------------------------------------

    def reference_ingredients(self) -> List[Dict[str, Any]]:
        """One row per ingredient name (the lowest id where a name sits in
        several categories), with its per-100 g nutrients. Rows without data
        (pills dosed per tablet and the like) are left out."""
        now = time.monotonic()
        if self._reference_cache and now - self._reference_cache[0] < REFERENCE_CACHE_SECONDS:
            return self._reference_cache[1]
        rows = (
            self.client.table(REFERENCE_TABLE).select(REFERENCE_COLUMNS)
            .neq("data_quality", "no data").order("id").execute().data
        )
        canonical: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            canonical.setdefault(row["name"], row)
        result = list(canonical.values())
        self._reference_cache = (now, result)
        return result

    # --- meal logs -------------------------------------------------------

    def create_meal_log(self, user_id: str, logged_for: date) -> Dict[str, Any]:
        return self.client.table("meal_logs").insert(
            {"user_id": user_id, "logged_for": logged_for.isoformat()}
        ).execute().data[0]

    def update_meal_log(self, meal_log_id: int, fields: Dict[str, Any]) -> None:
        self.client.table("meal_logs").update(fields).eq("id", meal_log_id).execute()

    def finish_meal_log(self, meal_log_id: int, fields: Dict[str, Any]) -> bool:
        """Set a processed log's outcome, but only while it's still
        `processing` — one she discarded meanwhile stays discarded. False if
        nothing was updated."""
        rows = (
            self.client.table("meal_logs").update(fields)
            .eq("id", meal_log_id).eq("status", "processing").execute().data
        )
        return bool(rows)

    def get_meal_log(self, meal_log_id: int) -> Optional[Dict[str, Any]]:
        rows = self.client.table("meal_logs").select("*").eq("id", meal_log_id).limit(1).execute().data
        return rows[0] if rows else None

    def get_meal_log_detail(self, meal_log_id: int) -> Optional[Dict[str, Any]]:
        rows = self.client.table("meal_logs").select(LOG_SELECT).eq("id", meal_log_id).limit(1).execute().data
        return rows[0] if rows else None

    def discard_meal_log(self, meal_log_id: int) -> None:
        """She threw a log away (Record again / Remove). Kept as `discarded`,
        hidden everywhere, so what it cost still counts in the admin Costs
        tab; its recording is removed separately."""
        self.client.table("meal_logs").update(
            {"status": "discarded", "audio_path": None}
        ).eq("id", meal_log_id).execute()

    def list_meal_logs(self, user_id: str, start: date, end: date) -> List[Dict[str, Any]]:
        """Her logs for the days start..end (inclusive), oldest first."""
        return (
            self.client.table("meal_logs").select(LOG_SELECT)
            .eq("user_id", user_id).neq("status", "discarded")
            .gte("logged_for", start.isoformat()).lte("logged_for", end.isoformat())
            .order("created_at")
            .execute().data
        )

    # --- logged items ----------------------------------------------------

    def replace_items(self, meal_log_id: int, items: List[Dict[str, Any]]) -> None:
        """Write a log's items (each with its `ingredients`: [{reference_id,
        ingredient_name, grams}]), replacing any from an earlier attempt at
        the same log."""
        self.client.table("meal_log_items").delete().eq("meal_log_id", meal_log_id).execute()
        for item in items:
            row = {key: value for key, value in item.items() if key != "ingredients"}
            item_id = self.client.table("meal_log_items").insert(
                {**row, "meal_log_id": meal_log_id}
            ).execute().data[0]["id"]
            self.set_item_ingredients(item_id, [
                {**line, "default_grams": line["grams"], "edited": False} for line in item.get("ingredients") or []
            ])

    def get_item(self, item_id: int) -> Optional[Dict[str, Any]]:
        """One logged item with its ingredient rows (and their reference
        values) and its log (for the owner check)."""
        rows = (
            self.client.table("meal_log_items").select(f"{ITEM_SELECT}, meal_logs(user_id, status, logged_for)")
            .eq("id", item_id).limit(1).execute().data
        )
        return rows[0] if rows else None

    def update_item(self, item_id: int, fields: Dict[str, Any]) -> None:
        self.client.table("meal_log_items").update(fields).eq("id", item_id).execute()

    def delete_item(self, item_id: int) -> None:
        self.client.table("meal_log_items").delete().eq("id", item_id).execute()

    def set_item_ingredients(self, item_id: int, rows: List[Dict[str, Any]]) -> None:
        """Insert or update an item's ingredient rows ([{reference_id,
        ingredient_name, grams, default_grams, edited}])."""
        if rows:
            self.client.table("meal_log_item_ingredients").upsert(
                [{"meal_log_item_id": item_id, **row} for row in rows],
                on_conflict="meal_log_item_id,reference_id",
            ).execute()

    # --- switched on per client ------------------------------------------

    def is_enabled(self, user_id: str) -> bool:
        """Whether the coach switched diet tracking on for this client
        (user_profiles.diet_enabled, off by default)."""
        rows = (
            self.client.table("user_profiles").select("diet_enabled")
            .eq("user_id", user_id).limit(1).execute().data
        )
        return bool(rows) and rows[0].get("diet_enabled") is True

    def set_enabled(self, user_id: str, enabled: bool) -> bool:
        """False if there's no such user."""
        rows = (
            self.client.table("user_profiles").update({"diet_enabled": enabled})
            .eq("user_id", user_id).execute().data
        )
        return bool(rows)

    # --- targets ---------------------------------------------------------

    def get_targets(self, user_id: str) -> Optional[Dict[str, Any]]:
        rows = (
            self.client.table("user_profiles").select("nutrition_targets")
            .eq("user_id", user_id).limit(1).execute().data
        )
        return rows[0].get("nutrition_targets") if rows else None

    def set_targets(self, user_id: str, targets: Optional[Dict[str, Any]]) -> bool:
        """False if there's no such user."""
        rows = (
            self.client.table("user_profiles").update({"nutrition_targets": targets})
            .eq("user_id", user_id).execute().data
        )
        return bool(rows)

    # --- one-time setup --------------------------------------------------

    def get_profile_basics(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Her gender and stored setup (None if there's no such user)."""
        rows = (
            self.client.table("user_profiles").select("gender, diet_setup")
            .eq("user_id", user_id).limit(1).execute().data
        )
        return rows[0] if rows else None

    def save_setup(self, user_id: str, setup: Dict[str, Any], targets: Dict[str, Any]) -> bool:
        """Store her setup and the targets it worked out, only if she hasn't
        done it before (one conditional update, so a double tap can't do it
        twice). False if it was already done."""
        rows = (
            self.client.table("user_profiles")
            .update({"diet_setup": setup, "nutrition_targets": targets})
            .eq("user_id", user_id).is_("diet_setup", "null").execute().data
        )
        return bool(rows)
