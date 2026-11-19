"""What the diet endpoints do with stored rows: shape logs and items for
the screens, total a day, and apply her edits (portion size, an
ingredient's amount, back to the estimate). Every edit recomputes the
item's stored nutrients from its ingredient rows."""
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from diet.nutrition import (
    DEFAULT_TARGETS, WEIGHT_UNITS, add_totals, display_unit, empty_totals, nutrients_of, rounded, targets_for,
)
from diet.repository import REFERENCE_TABLE, DietRepository

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


def _rows(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    return item.get("meal_log_item_ingredients") or []


def item_nutrients(item: Dict[str, Any]) -> Dict[str, float]:
    """The item's stored nutrient totals (every key, missing ones 0)."""
    return add_totals(empty_totals(), item.get("nutrients"))


def shape_item(item: Dict[str, Any], detail: bool = False, nutrients: bool = False) -> Dict[str, Any]:
    """A logged item for the screens. `detail` adds its ingredients (her
    ingredient screen, the coach's view); `nutrients` adds every nutrient
    (coach only — she gets just protein and fibre)."""
    totals = item_nutrients(item)
    shaped = {
        "id": item["id"],
        "name": item["dish_name"],
        "meal": item.get("meal"),
        "quantity": float(item["quantity"]),
        "unit": item["unit"],
        "grams": float(item["portion_grams"]) if item.get("portion_grams") is not None else None,
        "assumed": bool(item.get("assumed")),
        "needs_review": bool(item.get("needs_review")),
        "edited": bool(item.get("edited")),
        "protein_g": round(totals["protein_g"], 1),
        "fibre_g": round(totals["fibre_g"], 1),
        "energy_kcal": round(totals["energy_kcal"]),
    }
    if nutrients:
        shaped["nutrients"] = rounded(totals)
        shaped["quote"] = item.get("quote")
    if detail:
        ingredients = []
        for row in _rows(item):
            reference = row.get(REFERENCE_TABLE) or {}
            unit, per_unit = display_unit(reference.get("category"), row.get("ingredient_name"))
            ingredients.append({
                "ingredient_id": row["reference_id"],
                "name": row.get("ingredient_name"),
                "grams": float(row["grams"]),
                "default_grams": float(row["default_grams"]),
                "edited": bool(row.get("edited")),
                "display_unit": unit,
                "grams_per_display_unit": per_unit,
            })
        shaped["ingredients"] = sorted(ingredients, key=lambda row: -row["default_grams"])
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
                add_totals(totals, item.get("nutrients"))
    return totals


def _goal_totals(totals: Dict[str, float]) -> Dict[str, float]:
    """The totals her screen shows: calories and the four goal nutrients."""
    return {key: round(totals[key], 0 if key == "energy_kcal" else 1) for key in DEFAULT_TARGETS}


def day_summary(logs: List[Dict[str, Any]], stored_targets: Optional[Dict[str, Any]], day: str) -> Dict[str, Any]:
    """Her view of one day: calories, protein, fibre, carbs and fat against
    her targets, and the day's logs."""
    return {
        "date": day,
        "totals": _goal_totals(totals_of(logs)),
        "targets": targets_for(stored_targets),
        "logs": [shape_log(log) for log in logs],
    }


def recent_days(logs: List[Dict[str, Any]], end: date, days: int) -> List[Dict[str, Any]]:
    """The `days` days up to `end`, newest first, each with its totals and
    how many dishes she logged (0 for a day with nothing)."""
    by_day: Dict[str, List[Dict[str, Any]]] = {}
    for log in logs:
        by_day.setdefault(log["logged_for"], []).append(log)
    result = []
    for offset in range(days):
        day = (end - timedelta(days=offset)).isoformat()
        day_logs = by_day.get(day, [])
        result.append({
            "date": day,
            "totals": _goal_totals(totals_of(day_logs)),
            "dishes": sum(len(log.get("meal_log_items") or []) for log in day_logs
                          if log["status"] in COUNTED_STATUSES),
        })
    return result


class EditError(ValueError):
    """Why an edit can't be applied (shown to the client)."""


def _save(repo: DietRepository, item: Dict[str, Any], rows: List[Dict[str, Any]], fields: Dict[str, Any]) -> None:
    """Write new ingredient amounts and the item's fields, with its
    nutrients recomputed from those amounts."""
    repo.set_item_ingredients(item["id"], [
        {key: row[key] for key in ("reference_id", "ingredient_name", "grams", "default_grams", "edited")}
        for row in rows
    ])
    totals = nutrients_of({"grams": row["grams"], "reference": row.get(REFERENCE_TABLE)} for row in rows)
    repo.update_item(item["id"], {**fields, "nutrients": rounded(totals, 3)})


def change_quantity(repo: DietRepository, item: Dict[str, Any], quantity: float) -> None:
    """A different portion of the same dish: its weight and every
    ingredient amount scale with it."""
    # An amount said in grams or ml is a weight, not a count of servings.
    low, high = (1, MAX_INGREDIENT_GRAMS) if item["unit"] in WEIGHT_UNITS else (MIN_QUANTITY, MAX_QUANTITY)
    if not low <= quantity <= high:
        raise EditError(f"Quantity must be between {low} and {high}.")
    ratio = quantity / float(item["quantity"])
    fields: Dict[str, Any] = {"quantity": quantity, "edited": True, "assumed": False}
    if item.get("portion_grams") is not None:
        fields["portion_grams"] = round(float(item["portion_grams"]) * ratio, 1)
    rows = [
        {**row, "grams": round(float(row["grams"]) * ratio, 2),
         "default_grams": round(float(row["default_grams"]) * ratio, 2)}
        for row in _rows(item)
    ]
    _save(repo, item, rows, fields)


def change_ingredient(repo: DietRepository, item: Dict[str, Any], ingredient_id: int, grams: float) -> None:
    """She changed how much of one ingredient is in this dish (0 removes
    it). Only this entry changes."""
    if not 0 <= grams <= MAX_INGREDIENT_GRAMS:
        raise EditError(f"Amount must be between 0 and {MAX_INGREDIENT_GRAMS} g.")
    rows = _rows(item)
    if not any(row["reference_id"] == ingredient_id for row in rows):
        raise EditError("That ingredient isn't in this dish.")
    rows = [
        {**row, "grams": round(grams, 2), "edited": True} if row["reference_id"] == ingredient_id else row
        for row in rows
    ]
    _save(repo, item, rows, {"edited": True})


def reset_item(repo: DietRepository, item: Dict[str, Any]) -> None:
    """Back to the estimate: every ingredient to the amount first worked
    out for this portion."""
    rows = _rows(item)
    if not rows:
        raise EditError("This dish has no ingredients to reset.")
    rows = [{**row, "grams": float(row["default_grams"]), "edited": False} for row in rows]
    _save(repo, item, rows, {})
