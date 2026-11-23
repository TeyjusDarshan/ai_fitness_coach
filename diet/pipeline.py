"""One meal log, from recording to items: transcribe -> Sonnet lists the
dishes with the raw grams of each ingredient in her portion (names from
`ingredient_nutrition_reference` only) -> validate -> work out every
nutrient from the reference values -> save the dishes, their ingredient
rows and their nutrient totals.

Used by the voice processor (voice_processor/main.py, for meal-log-events)
and the dry run (diet/dry_run.py).
"""
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from diet import agent
from diet.nutrition import name_key, nutrients_of, rounded
from diet.repository import DietRepository
from diet.validate import validate_meal, validate_skipped

logger = logging.getLogger(__name__)

# meal_logs.error codes the PWA turns into a message.
NO_SPEECH, NO_FOOD, FAILED = "no_speech", "no_food", "failed"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def estimate(
    repo: DietRepository, transcript: str, user_id: Optional[str],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """(dishes, skipped meals) in a transcript: the validated dishes (see
    validate.validate_meal, each ingredient line carrying its reference row)
    and the meals she said she didn't eat (validate.validate_skipped)."""
    reference = repo.reference_ingredients()
    proposed = agent.estimate_meal(transcript, [row["name"] for row in reference], user_id)
    by_key = {name_key(row["name"]): row for row in reference}
    skipped = validate_skipped(getattr(proposed, "skipped_meals", None))
    return validate_meal(proposed.dishes, transcript, by_key), skipped


def build_item_rows(dishes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """meal_log_items rows (each with its `ingredients`) for validated
    dishes, with the dish's nutrients worked out from the reference values."""
    rows = []
    for dish in dishes:
        rows.append({
            "dish_name": dish["dish_name"],
            "dish_name_ta": dish["dish_name_ta"],
            "meal": dish["meal"],
            "quote": dish["quote"],
            "quantity": dish["quantity"],
            "unit": dish["unit"],
            "portion_grams": dish["portion_grams"],
            "assumed": dish["assumed"],
            "needs_review": dish["needs_review"],
            "nutrients": rounded(nutrients_of(dish["ingredients"]), 3),
            "ingredients": [
                {"reference_id": line["reference"]["id"], "ingredient_name": line["reference"]["name"],
                 "grams": line["grams"]}
                for line in dish["ingredients"]
            ],
        })
    return rows


def process_meal_log(repo: DietRepository, meal_log_id: int, transcribe: Callable[[Dict[str, Any]], str]) -> None:
    """Turn a `processing` meal log into items and mark it `ready`, or
    `failed` with a reason. `transcribe(log)` returns the recording's
    transcript. A log that isn't `processing` any more (redelivered event,
    or she discarded it) is left alone."""
    log = repo.get_meal_log(meal_log_id)
    if log is None or log["status"] != "processing":
        logger.info("Skipping meal_log_id=%s (missing or already processed)", meal_log_id)
        return

    def fail(error: str) -> None:
        repo.finish_meal_log(meal_log_id, {"status": "failed", "error": error, "processed_at": _now()})

    try:
        transcript = (transcribe(log) or "").strip()
        if not transcript:
            return fail(NO_SPEECH)
        repo.update_meal_log(meal_log_id, {"transcript": transcript})

        dishes, skipped = estimate(repo, transcript, log["user_id"])
        # "I skipped breakfast" is an answer too: a log with only skipped
        # meals is ready (no dishes, no nutrients), so it's acknowledged
        # and the meal reminders stop asking about that meal.
        if not dishes and not skipped:
            return fail(NO_FOOD)
        repo.update_meal_log(meal_log_id, {"skipped_meals": skipped})
        repo.replace_items(meal_log_id, build_item_rows(dishes))
        repo.finish_meal_log(meal_log_id, {
            "status": "ready", "error": None, "processed_at": _now(), "model": agent.MEAL_MODEL,
        })
        logger.info("Processed meal_log_id=%s: %d dishes, skipped %s", meal_log_id, len(dishes), skipped)
    except Exception:
        logger.exception("Failed to process meal_log_id=%s", meal_log_id)
        fail(FAILED)
