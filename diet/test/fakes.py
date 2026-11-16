"""An in-memory stand-in for DietRepository, and builders for what the
Claude calls return."""
from types import SimpleNamespace
from typing import Any, Dict, List

from diet.nutrition import MICROS

RICE = {"id": 1, "name": "Raw Rice", "name_key": "raw rice", "energy_kcal": 350, "protein_g": 7, "carbs_g": 78,
        "fibre_g": 1, "fat_g": 0.5, "saturated_fat_g": 0.1, "unsaturated_fat_g": 0.3, "calcium_mg": 10,
        "display_unit": None, "grams_per_display_unit": None}
OIL = {"id": 2, "name": "Gingelly Oil", "name_key": "gingelly oil", "energy_kcal": 900, "protein_g": 0,
       "carbs_g": 0, "fibre_g": 0, "fat_g": 100, "saturated_fat_g": 15, "unsaturated_fat_g": 80,
       "display_unit": "teaspoon", "grams_per_display_unit": 5}


class FakeRepo:
    def __init__(self):
        self.ingredients: Dict[int, Dict[str, Any]] = {1: dict(RICE), 2: dict(OIL)}
        self.foods: Dict[int, Dict[str, Any]] = {}
        self.user_recipes: Dict[Any, List[Dict[str, Any]]] = {}
        self.logs: Dict[int, Dict[str, Any]] = {}
        self.items: Dict[int, Dict[str, Any]] = {}

    # --- set-up helpers ---
    def add_food(self, name, portions, recipe, default_unit=None):
        food_id = len(self.foods) + 1
        self.foods[food_id] = {
            "id": food_id, "name": name, "name_key": name.casefold(), "aliases": [],
            "default_unit": default_unit or next(iter(portions)), "portions": dict(portions),
            "recipe": [{"ingredient_id": i, "grams_per_100g": g} for i, g in recipe.items()],
        }
        return food_id

    def add_log(self, user_id="usr_1", status="processing", **fields):
        log_id = len(self.logs) + 1
        self.logs[log_id] = {"id": log_id, "user_id": user_id, "status": status, "logged_for": "2026-11-16",
                             "audio_path": f"meal_{log_id}.webm", "transcript": None, "error": None,
                             "created_at": "2026-11-16T05:00:00+00:00", **fields}
        return log_id

    # --- DietRepository ---
    def get_meal_log(self, meal_log_id):
        return self.logs.get(meal_log_id)

    def update_meal_log(self, meal_log_id, fields):
        self.logs[meal_log_id].update(fields)

    def food_catalogue(self):
        return [{"id": f["id"], "name": f["name"], "aliases": f["aliases"]} for f in self.foods.values()]

    def get_foods(self, food_ids):
        return {i: self.foods[i] for i in set(food_ids) if i in self.foods}

    def find_food_ids(self, name_keys):
        keys = set(name_keys)
        return {f["name_key"]: f["id"] for f in self.foods.values() if f["name_key"] in keys}

    def insert_food(self, dish, model, meal_log_id):
        existing = self.find_food_ids([dish["name_key"]])
        if existing:
            return existing[dish["name_key"]]
        food_id = len(self.foods) + 1
        self.foods[food_id] = {**dish, "id": food_id}
        return food_id

    def upsert_portion(self, food_id, unit, grams, source="ai_estimate"):
        self.foods[food_id]["portions"][unit] = grams

    def ingredient_catalogue(self):
        return [{"id": i["id"], "name": i["name"], "name_key": i["name_key"]} for i in self.ingredients.values()]

    def insert_ingredient(self, row, model):
        ingredient_id = len(self.ingredients) + 1
        self.ingredients[ingredient_id] = {**row, "id": ingredient_id}
        return ingredient_id

    def get_user_recipes(self, user_id, food_ids):
        return {i: self.user_recipes[(user_id, i)] for i in set(food_ids) if (user_id, i) in self.user_recipes}

    def replace_user_recipe(self, user_id, food_id, recipe):
        self.user_recipes[(user_id, food_id)] = recipe

    def delete_user_recipe(self, user_id, food_id):
        self.user_recipes.pop((user_id, food_id), None)

    def replace_items(self, meal_log_id, items):
        self.items = {i: item for i, item in self.items.items() if item["meal_log_id"] != meal_log_id}
        for item in items:
            item_id = len(self.items) + 1
            row = {key: value for key, value in item.items() if key != "ingredients"}
            self.items[item_id] = {**row, "id": item_id, "meal_log_id": meal_log_id, "edited": False,
                                   "meal_log_item_ingredients": []}
            self.set_item_ingredients(item_id, [
                {**line, "default_grams": line["grams"], "edited": False} for line in item["ingredients"]
            ])

    def get_item(self, item_id):
        item = self.items.get(item_id)
        if item is None:
            return None
        return {**item, "meal_logs": self.logs.get(item["meal_log_id"]), "meal_log_item_ingredients": [
            {**row, "ingredients": self.ingredients[row["ingredient_id"]]}
            for row in item["meal_log_item_ingredients"]
        ]}

    def update_item(self, item_id, fields):
        self.items[item_id].update(fields)

    def set_item_ingredients(self, item_id, rows):
        current = {row["ingredient_id"]: row for row in self.items[item_id]["meal_log_item_ingredients"]}
        current.update({row["ingredient_id"]: dict(row) for row in rows})
        self.items[item_id]["meal_log_item_ingredients"] = list(current.values())

    def clear_item_ingredients(self, item_id):
        self.items[item_id]["meal_log_item_ingredients"] = []

    def log_items(self, meal_log_id):
        return [self.get_item(i) for i, item in self.items.items() if item["meal_log_id"] == meal_log_id]


def parsed(*items):
    """A ParsedMeal-like object: each item is (quote, food_id, name,
    quantity, unit[, stated[, meal]])."""
    out = []
    for item in items:
        quote, food_id, name, quantity, unit, *rest = item
        out.append(SimpleNamespace(
            quote=quote, food_id=food_id, food_name=name, quantity=quantity, unit=unit,
            quantity_stated=rest[0] if rest else True, meal=rest[1] if len(rest) > 1 else None,
        ))
    return SimpleNamespace(items=out)


def new_ingredient(name, protein=2.0, carbs=10.0, fat=1.0, **overrides):
    values = {"name": name, "aliases": [], "energy_kcal": 4 * protein + 4 * carbs + 9 * fat, "protein_g": protein,
              "carbs_g": carbs, "fibre_g": 1.0, "fat_g": fat, "saturated_fat_g": fat * 0.3,
              "unsaturated_fat_g": fat * 0.6, "display_unit": None, "grams_per_display_unit": None,
              **{key: None for key in MICROS}}
    return SimpleNamespace(**{**values, **overrides})


def new_dish(name, portions, ingredients, default_unit=None, aliases=()):
    """ingredients: [(ingredient_id or None, name, grams_per_100g)]."""
    return SimpleNamespace(
        name=name, aliases=list(aliases), default_unit=default_unit or next(iter(portions), "cup"),
        portions=[SimpleNamespace(unit=unit, grams=grams) for unit, grams in portions.items()],
        ingredients=[SimpleNamespace(ingredient_id=i, name=n, grams_per_100g=g) for i, n, g in ingredients],
    )


def estimation(dishes=(), ingredients=(), portions=()):
    return SimpleNamespace(
        dishes=list(dishes), new_ingredients=list(ingredients),
        portions_for_known_dishes=[SimpleNamespace(food_id=f, unit=u, grams=g) for f, u, g in portions],
    )
