"""An in-memory stand-in for DietRepository, and a builder for what the
Claude call returns."""
from types import SimpleNamespace
from typing import Any, Dict

from diet.nutrition import nutrients_of, rounded
from diet.repository import REFERENCE_TABLE

RICE = {"id": 1, "name": "Raw white rice", "category": "carb", "energy_kcal": 350, "protein_g": 7, "carbs_g": 78,
        "fibre_g": 1, "fat_g": 0.5, "saturated_fat_g": 0.1, "calcium_mg": 10}
OIL = {"id": 2, "name": "Sesame (gingelly) oil", "category": "oil_ghee", "energy_kcal": 900, "protein_g": 0,
       "carbs_g": 0, "fibre_g": 0, "fat_g": 100, "saturated_fat_g": 14.2}
URAD = {"id": 3, "name": "Urad dal", "category": "veg_protein", "energy_kcal": 327, "protein_g": 24,
        "carbs_g": 59.6, "fibre_g": 11, "fat_g": 1.6, "saturated_fat_g": 0.1}
# The same name in a second category (the reference table repeats some).
RICE_AGAIN = {**RICE, "id": 9, "category": "grain"}


class FakeRepo:
    def __init__(self):
        self.reference = {row["id"]: dict(row) for row in (RICE, OIL, URAD, RICE_AGAIN)}
        self.logs: Dict[int, Dict[str, Any]] = {}
        self.items: Dict[int, Dict[str, Any]] = {}
        self.enabled = set()

    def is_enabled(self, user_id):
        return user_id in self.enabled

    def set_enabled(self, user_id, enabled):
        (self.enabled.add if enabled else self.enabled.discard)(user_id)
        return True

    # One-time setup: user_id -> {gender, diet_setup}; targets saved with it.
    profiles: Dict[str, Dict[str, Any]]
    saved_targets: Dict[str, Any]

    def get_profile_basics(self, user_id):
        return getattr(self, "profiles", {}).get(user_id, {"gender": None, "diet_setup": None})

    def save_setup(self, user_id, setup, targets):
        self.profiles = getattr(self, "profiles", {})
        profile = self.profiles.setdefault(user_id, {"gender": None, "diet_setup": None})
        if profile["diet_setup"] is not None:
            return False
        profile["diet_setup"] = setup
        self.saved_targets = {**getattr(self, "saved_targets", {}), user_id: targets}
        return True

    # --- set-up helpers ---
    def add_log(self, user_id="usr_1", status="processing", **fields):
        log_id = len(self.logs) + 1
        self.logs[log_id] = {"id": log_id, "user_id": user_id, "status": status, "logged_for": "2026-11-16",
                             "audio_path": f"meal_{log_id}.webm", "transcript": None, "error": None,
                             "created_at": "2026-11-16T05:00:00+00:00", **fields}
        return log_id

    def add_item(self, meal_log_id, dish_name, grams_by_reference, **fields):
        """A logged dish as the pipeline would save it: ingredient rows and
        their nutrient totals."""
        lines = [{"reference": self.reference[ref_id], "grams": grams} for ref_id, grams in grams_by_reference.items()]
        item = {
            "dish_name": dish_name, "meal": None, "quote": dish_name, "quantity": 1, "unit": "piece",
            "portion_grams": 100, "assumed": False, "needs_review": False,
            "nutrients": rounded(nutrients_of(lines), 3),
            "ingredients": [
                {"reference_id": line["reference"]["id"], "ingredient_name": line["reference"]["name"],
                 "grams": line["grams"]} for line in lines
            ],
            **fields,
        }
        self._insert(meal_log_id, item)
        return max(self.items)

    # --- DietRepository ---
    def reference_ingredients(self):
        canonical = {}
        for row in sorted(self.reference.values(), key=lambda r: r["id"]):
            canonical.setdefault(row["name"], row)
        return list(canonical.values())

    def get_meal_log(self, meal_log_id):
        return self.logs.get(meal_log_id)

    def update_meal_log(self, meal_log_id, fields):
        self.logs[meal_log_id].update(fields)

    def finish_meal_log(self, meal_log_id, fields):
        if self.logs[meal_log_id]["status"] != "processing":
            return False
        self.logs[meal_log_id].update(fields)
        return True

    def discard_meal_log(self, meal_log_id):
        self.logs[meal_log_id].update(status="discarded", audio_path=None)

    def _insert(self, meal_log_id, item):
        item_id = max(self.items, default=0) + 1
        row = {key: value for key, value in item.items() if key != "ingredients"}
        self.items[item_id] = {**row, "id": item_id, "meal_log_id": meal_log_id, "edited": False,
                               "meal_log_item_ingredients": []}
        self.set_item_ingredients(item_id, [
            {**line, "default_grams": line["grams"], "edited": False} for line in item["ingredients"]
        ])

    def replace_items(self, meal_log_id, items):
        self.items = {i: item for i, item in self.items.items() if item["meal_log_id"] != meal_log_id}
        for item in items:
            self._insert(meal_log_id, item)

    def get_item(self, item_id):
        item = self.items.get(item_id)
        if item is None:
            return None
        return {**item, "meal_logs": self.logs.get(item["meal_log_id"]), "meal_log_item_ingredients": [
            {**row, REFERENCE_TABLE: self.reference[row["reference_id"]]}
            for row in item["meal_log_item_ingredients"]
        ]}

    def update_item(self, item_id, fields):
        self.items[item_id].update(fields)

    def delete_item(self, item_id):
        self.items.pop(item_id)

    def set_item_ingredients(self, item_id, rows):
        current = {row["reference_id"]: row for row in self.items[item_id]["meal_log_item_ingredients"]}
        current.update({row["reference_id"]: dict(row) for row in rows})
        self.items[item_id]["meal_log_item_ingredients"] = list(current.values())

    def log_items(self, meal_log_id):
        return [self.get_item(i) for i, item in self.items.items() if item["meal_log_id"] == meal_log_id]


def dish(quote, name, quantity, unit, portion_grams, ingredients, stated=True, meal=None, name_ta=None):
    """One dish as Claude returns it; `ingredients` is [(name, grams)]."""
    return SimpleNamespace(
        quote=quote, dish_name=name, dish_name_ta=name_ta, quantity=quantity, unit=unit, quantity_stated=stated, meal=meal,
        portion_grams=portion_grams,
        ingredients=[SimpleNamespace(name=n, grams=g) for n, g in ingredients],
    )


def estimate(*dishes, skipped=()):
    return SimpleNamespace(dishes=list(dishes), skipped_meals=list(skipped))
