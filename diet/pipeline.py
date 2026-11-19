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
from typing import Any, Callable, Dict, List, Optional

from diet import agent
from diet.nutrition import name_key, nutrients_of, rounded
from diet.repository import DietRepository
from diet.validate import validate_meal

logger = logging.getLogger(__name__)

# meal_logs.error codes the PWA turns into a message.
NO_SPEECH, NO_FOOD, FAILED = "no_speech", "no_food", "failed"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def estimate(repo: DietRepository, transcript: str, user_id: Optional[str]) -> List[Dict[str, Any]]:
    """The validated dishes in a transcript (see validate.validate_meal),
    each ingredient line carrying its reference row."""
    reference = repo.reference_ingredients()
    proposed = agent.estimate_meal(transcript, [row["name"] for row in reference], user_id)
    by_key = {name_key(row["name"]): row for row in reference}
    return validate_meal(proposed.dishes, transcript, by_key)


def build_item_rows(dishes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """meal_log_items rows (each with its `ingredients`) for validated
    dishes, with the dish's nutrients worked out from the reference values."""
    rows = []
    for dish in dishes:
        rows.append({
            "dish_name": dish["dish_name"],
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

        dishes = estimate(repo, transcript, log["user_id"])
        if not dishes:
            return fail(NO_FOOD)
        repo.replace_items(meal_log_id, build_item_rows(dishes))
        repo.finish_meal_log(meal_log_id, {
            "status": "ready", "error": None, "processed_at": _now(), "model": agent.MEAL_MODEL,
        })
        logger.info("Processed meal_log_id=%s: %d dishes", meal_log_id, len(dishes))
    except Exception:
        logger.exception("Failed to process meal_log_id=%s", meal_log_id)
        fail(FAILED)
