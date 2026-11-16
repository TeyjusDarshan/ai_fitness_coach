"""One meal log, from recording to items: transcribe -> parse against the
known dishes -> add any dish (and ingredient) nobody has logged before ->
work out grams -> copy each dish's recipe (her own version if she has one)
onto the item as ingredient rows.

Used by the voice processor (voice_processor/main.py, for meal-log-events)
and the dry run (diet/dry_run.py).
"""
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from diet import agent
from diet.nutrition import PORTION_UNITS, name_key, portion_grams, scale_recipe
from diet.repository import DietRepository
from diet.validate import (
    MAX_PORTION_GRAMS, MIN_PORTION_GRAMS, validate_dish, validate_ingredient, validate_items,
)

logger = logging.getLogger(__name__)

# meal_logs.error codes the PWA turns into a message.
NO_SPEECH, NO_FOOD, FAILED = "no_speech", "no_food", "failed"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_transcript(repo: DietRepository, transcript: str, user_id: Optional[str]) -> List[Dict[str, Any]]:
    """The validated items in a transcript (see validate.validate_items)."""
    catalogue = repo.food_catalogue()
    parsed = agent.parse_meal(transcript, catalogue, user_id)
    return validate_items(parsed.items, transcript, {food["id"] for food in catalogue})


def add_unknown_dishes(
    repo: DietRepository, items: List[Dict[str, Any]], user_id: Optional[str], meal_log_id: Optional[int]
) -> None:
    """Fill in `food_id` on the items naming a dish that isn't in the table
    yet, adding the dish (recipe, unit weights) and any new ingredients
    from Claude's estimate. Also adds a unit weight a known dish lacks
    (she said "plate", the dish only has "piece"). An item whose dish
    couldn't be added keeps food_id None. Best-effort: if the estimate
    fails, the known dishes still get logged."""
    unknown = {name_key(item["food_name"]): item["food_name"] for item in items if item["food_id"] is None}
    # Named differently enough that the parse didn't match it, but the same key.
    already = repo.find_food_ids(unknown)
    for item in items:
        if item["food_id"] is None:
            item["food_id"] = already.get(name_key(item["food_name"]))
    unknown = {key: name for key, name in unknown.items() if key not in already}

    foods = repo.get_foods(item["food_id"] for item in items)
    missing = {
        (item["food_id"], item["unit"]): foods[item["food_id"]]
        for item in items
        if item["food_id"] in foods and item["unit"] in PORTION_UNITS
        and item["unit"] not in foods[item["food_id"]]["portions"]
    }
    if not unknown and not missing:
        return

    try:
        ingredients = repo.ingredient_catalogue()
        estimation = agent.estimate(
            sorted(unknown.values()),
            [{"food_id": food_id, "name": food["name"], "unit": unit, "known_weights": food["portions"]}
             for (food_id, unit), food in missing.items()],
            [{"id": ingredient["id"], "name": ingredient["name"]} for ingredient in ingredients],
            user_id,
        )
    except Exception:
        logger.exception("Recipe estimation failed for dishes=%s", sorted(unknown.values()))
        return

    ingredient_ids = {ingredient["name_key"]: ingredient["id"] for ingredient in ingredients}
    for proposed in estimation.new_ingredients:
        row = validate_ingredient(proposed)
        if row is None:
            logger.warning("Dropped unusable ingredient estimate: %s", proposed.name)
        elif row["name_key"] not in ingredient_ids:
            ingredient_ids[row["name_key"]] = repo.insert_ingredient(row, agent.ESTIMATE_MODEL)

    added: Dict[str, int] = {}
    for proposed in estimation.dishes:
        key = name_key(proposed.name)
        if key not in unknown or key in added:
            continue
        dish = validate_dish(proposed, ingredient_ids)
        if dish is None:
            logger.warning("Dropped unusable dish estimate: %s", proposed.name)
            continue
        try:
            added[key] = repo.insert_food(dish, agent.ESTIMATE_MODEL, meal_log_id)
        except Exception:
            logger.exception("Failed to save dish %s", proposed.name)
    for item in items:
        if item["food_id"] is None:
            item["food_id"] = added.get(name_key(item["food_name"]))

    for portion in estimation.portions_for_known_dishes:
        if (portion.food_id, portion.unit) in missing and MIN_PORTION_GRAMS <= portion.grams <= MAX_PORTION_GRAMS:
            repo.upsert_portion(portion.food_id, portion.unit, round(portion.grams, 1))


def build_item_rows(repo: DietRepository, items: List[Dict[str, Any]], user_id: str) -> List[Dict[str, Any]]:
    """meal_log_items rows (each with its `ingredients`) for the validated
    items, once every dish that could be added has been."""
    foods = repo.get_foods(item["food_id"] for item in items)
    own_recipes = repo.get_user_recipes(user_id, foods)
    rows = []
    for item in items:
        food = foods.get(item["food_id"])
        row = {
            "food_id": food["id"] if food else None,
            "food_name": food["name"] if food else item["food_name"],
            "meal": item["meal"],
            "quote": item["quote"],
            "quantity": item["quantity"] or 1,
            "unit": item["unit"] or (food["default_unit"] if food else "piece"),
            "grams": None,
            "assumed": item["quantity"] is None,
            "needs_review": food is None,
            "used_own_recipe": False,
            "ingredients": [],
        }
        if food:
            grams = portion_grams(row["quantity"], row["unit"], food["portions"])
            if grams is None:
                # No weight for the unit she used: one default serving each.
                row["unit"], row["assumed"] = food["default_unit"], True
                grams = portion_grams(row["quantity"], row["unit"], food["portions"])
            row["grams"] = grams
            if grams is None:
                row["needs_review"] = True
            else:
                recipe = own_recipes.get(food["id"])
                row["used_own_recipe"] = recipe is not None
                row["ingredients"] = scale_recipe(recipe or food["recipe"], grams)
        rows.append(row)
    return rows


def process_meal_log(repo: DietRepository, meal_log_id: int, transcribe: Callable[[Dict[str, Any]], str]) -> None:
    """Turn a `processing` meal log into items and mark it `ready`, or
    `failed` with a reason. `transcribe(log)` returns the recording's
    transcript. A log that isn't `processing` any more (redelivered event,
    or she deleted it) is left alone."""
    log = repo.get_meal_log(meal_log_id)
    if log is None or log["status"] != "processing":
        logger.info("Skipping meal_log_id=%s (missing or already processed)", meal_log_id)
        return

    def fail(error: str) -> None:
        repo.update_meal_log(meal_log_id, {"status": "failed", "error": error, "processed_at": _now()})

    try:
        transcript = (transcribe(log) or "").strip()
        if not transcript:
            return fail(NO_SPEECH)
        repo.update_meal_log(meal_log_id, {"transcript": transcript})

        items = parse_transcript(repo, transcript, log["user_id"])
        if not items:
            return fail(NO_FOOD)
        add_unknown_dishes(repo, items, log["user_id"], meal_log_id)
        repo.replace_items(meal_log_id, build_item_rows(repo, items, log["user_id"]))
        repo.update_meal_log(meal_log_id, {"status": "ready", "error": None, "processed_at": _now()})
        logger.info("Processed meal_log_id=%s: %d items", meal_log_id, len(items))
    except Exception:
        logger.exception("Failed to process meal_log_id=%s", meal_log_id)
        fail(FAILED)
