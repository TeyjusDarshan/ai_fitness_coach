"""What the diet endpoints do with stored rows: shape logs and items for
the screens, total a day, and apply her edits (portion size, an
ingredient's amount, reset to the standard recipe)."""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from diet.nutrition import (
    WEIGHT_UNITS, add_totals, empty_totals, nutrients_of, recipe_from_amounts, rounded, scale_recipe, targets_for,
)
from diet.repository import DietRepository

# A log whose processing never finished (consumer down, a lost event) is
# shown as failed after this long, so she can record again.
PROCESSING_TIMEOUT = timedelta(minutes=5)
# Logs that count towards a day's totals — reviewed by her or not.
COUNTED_STATUSES = ("ready", "confirmed")

MIN_QUANTITY, MAX_QUANTITY = 0.25, 20
MAX_INGREDIENT_GRAMS = 2000


def log_status(log: Dict[str, Any], now: Optional[datetime] = None) -> str:
    if log["status"] == "processing":
        created = datetime.fromisoformat(log["created_at"].replace("Z", "+00:00"))
        if (now or datetime.now(timezone.utc)) - created > PROCESSING_TIMEOUT:
            return "failed"
    return log["status"]


def _ingredient_rows(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    """An item's ingredient rows as {grams, ingredient, ...} for nutrients_of."""
    return [{**row, "ingredient": row.get("ingredients") or {}} for row in item.get("meal_log_item_ingredients") or []]


def item_nutrients(item: Dict[str, Any]) -> Dict[str, float]:
    return nutrients_of(_ingredient_rows(item))


def shape_item(item: Dict[str, Any], detail: bool = False, nutrients: bool = False) -> Dict[str, Any]:
    """A logged item for the screens. `detail` adds its ingredients (her
    ingredient screen, the coach's view); `nutrients` adds every nutrient
    (coach only — she gets just protein and fibre)."""
    totals = item_nutrients(item)
    shaped = {
        "id": item["id"],
        "food_id": item.get("food_id"),
        "name": item["food_name"],
        "meal": item.get("meal"),
        "quantity": float(item["quantity"]),
        "unit": item["unit"],
        "grams": float(item["grams"]) if item.get("grams") is not None else None,
        "assumed": bool(item.get("assumed")),
        "needs_review": bool(item.get("needs_review")),
        "edited": bool(item.get("edited")),
        "own_recipe": bool(item.get("used_own_recipe")),
        "protein_g": round(totals["protein_g"], 1),
        "fibre_g": round(totals["fibre_g"], 1),
        "energy_kcal": round(totals["energy_kcal"]),
    }
    if nutrients:
        shaped["nutrients"] = rounded(totals)
        shaped["quote"] = item.get("quote")
    if detail:
        shaped["ingredients"] = sorted((
            {
                "ingredient_id": row["ingredient_id"],
                "name": (row.get("ingredients") or {}).get("name"),
                "grams": float(row["grams"]),
                "default_grams": float(row["default_grams"]),
                "edited": bool(row.get("edited")),
                "display_unit": (row.get("ingredients") or {}).get("display_unit"),
                "grams_per_display_unit": (row.get("ingredients") or {}).get("grams_per_display_unit"),
            }
            for row in item.get("meal_log_item_ingredients") or []
        ), key=lambda row: -row["default_grams"])
    return shaped


def shape_log(log: Dict[str, Any], detail: bool = False, nutrients: bool = False) -> Dict[str, Any]:
    items = sorted(log.get("meal_log_items") or [], key=lambda item: item["id"])
    status = log_status(log)
    shaped = {
        "id": log["id"],
        "logged_for": log["logged_for"],
        "status": status,
        # Why it failed: no_speech, no_food, failed, or timeout (never processed).
        "error": (log.get("error") or "timeout") if status == "failed" else None,
        "created_at": log["created_at"],
        "items": [shape_item(item, detail, nutrients) for item in items],
    }
    if nutrients:
        shaped["transcript"] = log.get("transcript")
        shaped["has_audio"] = bool(log.get("audio_path"))
    return shaped


def totals_of(logs: List[Dict[str, Any]]) -> Dict[str, float]:
    """Every nutrient across the counted logs' items."""
    totals = empty_totals()
    for log in logs:
        if log["status"] in COUNTED_STATUSES:
            for item in log.get("meal_log_items") or []:
                add_totals(totals, item_nutrients(item))
    return totals


def day_summary(logs: List[Dict[str, Any]], stored_targets: Optional[Dict[str, Any]], day: str) -> Dict[str, Any]:
    """Her simple view of one day: protein and fibre against her targets,
    and the day's logs."""
    totals = totals_of(logs)
    return {
        "date": day,
        "totals": {"protein_g": round(totals["protein_g"], 1), "fibre_g": round(totals["fibre_g"], 1)},
        "targets": targets_for(stored_targets),
        "logs": [shape_log(log) for log in logs],
    }


class EditError(ValueError):
    """Why an edit can't be applied (shown to the client)."""


def change_quantity(repo: DietRepository, item: Dict[str, Any], quantity: float) -> None:
    """A different portion of the same dish: the item's grams and every
    ingredient amount scale with it."""
    # An amount said in grams or ml is a weight, not a count of servings.
    low, high = (1, MAX_INGREDIENT_GRAMS) if item["unit"] in WEIGHT_UNITS else (MIN_QUANTITY, MAX_QUANTITY)
    if not low <= quantity <= high:
        raise EditError(f"Quantity must be between {low} and {high}.")
    ratio = quantity / float(item["quantity"])
    fields: Dict[str, Any] = {"quantity": quantity, "edited": True, "assumed": False}
    if item.get("grams") is not None:
        fields["grams"] = round(float(item["grams"]) * ratio, 1)
    repo.update_item(item["id"], fields)
    repo.set_item_ingredients(item["id"], [
        {
            "ingredient_id": row["ingredient_id"],
            "grams": round(float(row["grams"]) * ratio, 2),
            "default_grams": round(float(row["default_grams"]) * ratio, 2),
            "edited": bool(row.get("edited")),
        }
        for row in item.get("meal_log_item_ingredients") or []
    ])


def change_ingredient(repo: DietRepository, item: Dict[str, Any], user_id: str, ingredient_id: int,
                      grams: float) -> None:
    """She changed how much of one ingredient is in this dish (0 removes
    it). The entry changes, and the dish as she makes it — this entry's
    ingredient amounts per 100 g — becomes her version for future logs. The
    shared recipe isn't touched."""
    if not 0 <= grams <= MAX_INGREDIENT_GRAMS:
        raise EditError(f"Amount must be between 0 and {MAX_INGREDIENT_GRAMS} g.")
    rows = item.get("meal_log_item_ingredients") or []
    row = next((row for row in rows if row["ingredient_id"] == ingredient_id), None)
    if row is None:
        raise EditError("That ingredient isn't in this dish.")
    repo.set_item_ingredients(item["id"], [{
        "ingredient_id": ingredient_id, "grams": round(grams, 2),
        "default_grams": float(row["default_grams"]), "edited": True,
    }])
    repo.update_item(item["id"], {"edited": True, "used_own_recipe": True})
    if item.get("food_id") is not None and item.get("grams"):
        amounts = [
            {"ingredient_id": r["ingredient_id"], "grams": grams if r["ingredient_id"] == ingredient_id else r["grams"]}
            for r in rows
        ]
        repo.replace_user_recipe(user_id, item["food_id"], recipe_from_amounts(amounts, float(item["grams"])))


def reset_recipe(repo: DietRepository, item: Dict[str, Any], user_id: str) -> None:
    """Back to the standard recipe: her version of the dish is dropped and
    this entry's ingredients are rebuilt from the shared one."""
    food_id = item.get("food_id")
    if food_id is None or not item.get("grams"):
        raise EditError("This dish has no standard recipe yet.")
    food = repo.get_foods([food_id]).get(food_id)
    if not food or not food["recipe"]:
        raise EditError("This dish has no standard recipe yet.")
    repo.delete_user_recipe(user_id, food_id)
    repo.clear_item_ingredients(item["id"])
    repo.set_item_ingredients(item["id"], [
        {**line, "default_grams": line["grams"], "edited": False}
        for line in scale_recipe(food["recipe"], float(item["grams"]))
    ])
    repo.update_item(item["id"], {"used_own_recipe": False})
