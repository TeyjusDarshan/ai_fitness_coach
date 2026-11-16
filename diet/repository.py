"""Supabase reads and writes for diet tracking: the self-growing `foods`
(dishes, with `food_portions` and the `food_ingredients` recipe) and
`ingredients` tables, each client's own recipe versions
(`user_food_ingredients`), and her `meal_logs` -> `meal_log_items` ->
`meal_log_item_ingredients`."""
import os
from datetime import date
from typing import Any, Dict, Iterable, List, Optional

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

ITEM_SELECT = "*, meal_log_item_ingredients(*, ingredients(*))"
LOG_SELECT = f"*, meal_log_items({ITEM_SELECT})"
FOOD_SELECT = "*, food_portions(unit, grams, source), food_ingredients(ingredient_id, grams_per_100g)"


def _food(row: Dict[str, Any]) -> Dict[str, Any]:
    """A foods row with its unit weights as {unit: grams} and its recipe as
    [{ingredient_id, grams_per_100g}]."""
    return {
        **{key: value for key, value in row.items() if key not in ("food_portions", "food_ingredients")},
        "portions": {portion["unit"]: float(portion["grams"]) for portion in row.get("food_portions") or []},
        "recipe": [
            {"ingredient_id": line["ingredient_id"], "grams_per_100g": float(line["grams_per_100g"])}
            for line in row.get("food_ingredients") or []
        ],
    }


class DietRepository:
    def __init__(self, client: Optional[Client] = None):
        self.client = client or create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

    # --- meal logs -------------------------------------------------------

    def create_meal_log(self, user_id: str, logged_for: date) -> Dict[str, Any]:
        return self.client.table("meal_logs").insert(
            {"user_id": user_id, "logged_for": logged_for.isoformat()}
        ).execute().data[0]

    def update_meal_log(self, meal_log_id: int, fields: Dict[str, Any]) -> None:
        self.client.table("meal_logs").update(fields).eq("id", meal_log_id).execute()

    def get_meal_log(self, meal_log_id: int) -> Optional[Dict[str, Any]]:
        rows = self.client.table("meal_logs").select("*").eq("id", meal_log_id).limit(1).execute().data
        return rows[0] if rows else None

    def get_meal_log_detail(self, meal_log_id: int) -> Optional[Dict[str, Any]]:
        rows = self.client.table("meal_logs").select(LOG_SELECT).eq("id", meal_log_id).limit(1).execute().data
        return rows[0] if rows else None

    def delete_meal_log(self, meal_log_id: int) -> None:
        self.client.table("meal_logs").delete().eq("id", meal_log_id).execute()

    def list_meal_logs(self, user_id: str, start: date, end: date) -> List[Dict[str, Any]]:
        """Her logs for the days start..end (inclusive), oldest first."""
        return (
            self.client.table("meal_logs").select(LOG_SELECT)
            .eq("user_id", user_id)
            .gte("logged_for", start.isoformat()).lte("logged_for", end.isoformat())
            .order("created_at")
            .execute().data
        )

    # --- dishes ----------------------------------------------------------

    def food_catalogue(self) -> List[Dict[str, Any]]:
        """Every known dish as {id, name, aliases} — what the parse call
        matches her words against."""
        return self.client.table("foods").select("id, name, aliases").order("id").execute().data

    def get_foods(self, food_ids: Iterable[int]) -> Dict[int, Dict[str, Any]]:
        ids = sorted({food_id for food_id in food_ids if food_id is not None})
        if not ids:
            return {}
        rows = self.client.table("foods").select(FOOD_SELECT).in_("id", ids).execute().data
        return {row["id"]: _food(row) for row in rows}

    def find_food_ids(self, name_keys: Iterable[str]) -> Dict[str, int]:
        keys = sorted(set(name_keys))
        if not keys:
            return {}
        rows = self.client.table("foods").select("id, name_key").in_("name_key", keys).execute().data
        return {row["name_key"]: row["id"] for row in rows}

    def insert_food(self, dish: Dict[str, Any], model: Optional[str], meal_log_id: Optional[int]) -> int:
        """Add a validated dish (see validate.validate_dish) with its unit
        weights and recipe; returns its id. If another log added the same
        dish first, that one's id is returned and nothing is changed."""
        inserted = self.client.table("foods").upsert({
            "name": dish["name"], "name_key": dish["name_key"], "aliases": dish["aliases"],
            "default_unit": dish["default_unit"], "model": model, "created_from_meal_log_id": meal_log_id,
        }, on_conflict="name_key", ignore_duplicates=True).execute().data
        if not inserted:
            return self.find_food_ids([dish["name_key"]])[dish["name_key"]]
        food_id = inserted[0]["id"]
        try:
            self.client.table("food_portions").insert([
                {"food_id": food_id, "unit": unit, "grams": grams} for unit, grams in dish["portions"].items()
            ]).execute()
            self.client.table("food_ingredients").insert([
                {"food_id": food_id, **line} for line in dish["recipe"]
            ]).execute()
        except Exception:
            # A dish without its recipe would log as zero nutrients forever.
            self.client.table("foods").delete().eq("id", food_id).execute()
            raise
        return food_id

    def upsert_portion(self, food_id: int, unit: str, grams: float, source: str = "ai_estimate") -> None:
        self.client.table("food_portions").upsert(
            {"food_id": food_id, "unit": unit, "grams": grams, "source": source}, on_conflict="food_id,unit",
        ).execute()

    # --- ingredients -----------------------------------------------------

    def ingredient_catalogue(self) -> List[Dict[str, Any]]:
        return self.client.table("ingredients").select("id, name, name_key").order("id").execute().data

    def insert_ingredient(self, row: Dict[str, Any], model: Optional[str]) -> int:
        """Add a validated ingredient; returns its id (the existing one's if
        the name is already there)."""
        inserted = self.client.table("ingredients").upsert(
            {**row, "model": model}, on_conflict="name_key", ignore_duplicates=True,
        ).execute().data
        if inserted:
            return inserted[0]["id"]
        existing = self.client.table("ingredients").select("id").eq("name_key", row["name_key"]).execute().data
        return existing[0]["id"]

    # --- her own version of a dish ---------------------------------------

    def get_user_recipes(self, user_id: str, food_ids: Iterable[int]) -> Dict[int, List[Dict[str, Any]]]:
        """food_id -> her recipe, for the dishes she has her own version of."""
        ids = sorted({food_id for food_id in food_ids if food_id is not None})
        if not ids:
            return {}
        rows = (
            self.client.table("user_food_ingredients").select("food_id, ingredient_id, grams_per_100g")
            .eq("user_id", user_id).in_("food_id", ids).execute().data
        )
        recipes: Dict[int, List[Dict[str, Any]]] = {}
        for row in rows:
            recipes.setdefault(row["food_id"], []).append(
                {"ingredient_id": row["ingredient_id"], "grams_per_100g": float(row["grams_per_100g"])}
            )
        return recipes

    def replace_user_recipe(self, user_id: str, food_id: int, recipe: List[Dict[str, Any]]) -> None:
        self.delete_user_recipe(user_id, food_id)
        if recipe:
            self.client.table("user_food_ingredients").insert(
                [{"user_id": user_id, "food_id": food_id, **line} for line in recipe]
            ).execute()

    def delete_user_recipe(self, user_id: str, food_id: int) -> None:
        self.client.table("user_food_ingredients").delete().eq("user_id", user_id).eq("food_id", food_id).execute()

    # --- logged items ----------------------------------------------------

    def replace_items(self, meal_log_id: int, items: List[Dict[str, Any]]) -> None:
        """Write a log's items (each with its `ingredients`: [{ingredient_id,
        grams}]), replacing any from an earlier attempt at the same log."""
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
        """One logged item with its ingredient rows and its log (for the
        owner check)."""
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
        """Insert or update an item's ingredient rows ([{ingredient_id,
        grams, default_grams, edited}])."""
        if rows:
            self.client.table("meal_log_item_ingredients").upsert(
                [{"meal_log_item_id": item_id, **row} for row in rows],
                on_conflict="meal_log_item_id,ingredient_id",
            ).execute()

    def clear_item_ingredients(self, item_id: int) -> None:
        self.client.table("meal_log_item_ingredients").delete().eq("meal_log_item_id", item_id).execute()

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

    # --- coach: the food library -----------------------------------------

    def list_foods(self) -> List[Dict[str, Any]]:
        """Every dish with unit weights and recipe, unverified first."""
        rows = self.client.table("foods").select(FOOD_SELECT).order("verified").order("name").execute().data
        return [_food(row) for row in rows]

    def list_ingredients(self) -> List[Dict[str, Any]]:
        return self.client.table("ingredients").select("*").order("verified").order("name").execute().data

    def update_food(self, food_id: int, fields: Dict[str, Any], portions: Optional[Dict[str, float]],
                    recipe: Optional[List[Dict[str, Any]]]) -> bool:
        """The coach's correction of a dish: `fields` on the row, and — when
        given — the whole set of unit weights and/or the whole recipe.
        False if there's no such dish."""
        rows = self.client.table("foods").update(fields).eq("id", food_id).execute().data
        if not rows:
            return False
        if portions is not None:
            self.client.table("food_portions").delete().eq("food_id", food_id).execute()
            self.client.table("food_portions").insert([
                {"food_id": food_id, "unit": unit, "grams": grams, "source": "coach"}
                for unit, grams in portions.items()
            ]).execute()
        if recipe is not None:
            self.client.table("food_ingredients").delete().eq("food_id", food_id).execute()
            self.client.table("food_ingredients").insert(
                [{"food_id": food_id, **line} for line in recipe]
            ).execute()
        return True

    def update_ingredient(self, ingredient_id: int, fields: Dict[str, Any]) -> bool:
        rows = self.client.table("ingredients").update(fields).eq("id", ingredient_id).execute().data
        return bool(rows)

    def ingredient_ids(self) -> List[int]:
        return [row["id"] for row in self.client.table("ingredients").select("id").execute().data]
