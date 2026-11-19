"""The diet-tracking Claude call (structured output):

estimate_meal: her transcript + the ingredient names of
`ingredient_nutrition_reference` -> every dish she ate, with its portion and
the raw grams of each ingredient in that portion. Claude sees names only,
never nutrients; the ingredient `name` is an enum of those names, so it
can't name anything else. Nutrients are worked out in code (diet/nutrition.py).

It only proposes; diet/validate.py checks everything before it's stored.
"""
import json
import logging
import os
from functools import lru_cache
from typing import Any, List, Literal, Optional, Tuple

import anthropic
from ai_usage import record_claude
from dotenv import load_dotenv
from pydantic import BaseModel, create_model

from diet.prompts import MEAL_SYSTEM_PROMPT

load_dotenv()

logger = logging.getLogger(__name__)

MEAL_MODEL = "claude-sonnet-5-5"
FEATURE = "meal_estimation"

client = anthropic.Anthropic(timeout=float(os.getenv("DIET_AGENT_TIMEOUT_SECONDS", "120")))

Unit = Literal[
    "piece", "karandi", "cup", "tumbler", "tablespoon", "teaspoon", "plate", "bowl", "handful", "slice",
    "grams", "ml",
]
Meal = Literal["breakfast", "lunch", "dinner", "snack"]


class DietAgentRefusedError(RuntimeError):
    """Claude declined (and no fallback model took the request)."""


@lru_cache(maxsize=4)
def meal_schema(names: Tuple[str, ...]) -> type:
    """The output model for one ingredient list: the ingredient `name` is an
    enum of exactly those names."""
    ingredient = create_model("DishIngredient", name=(Literal[names], ...), grams=(float, ...))
    dish = create_model(
        "Dish",
        quote=(str, ...),
        dish_name=(str, ...),
        quantity=(float, ...),
        unit=(Unit, ...),
        quantity_stated=(bool, ...),
        meal=(Optional[Meal], ...),
        portion_grams=(float, ...),
        ingredients=(List[ingredient], ...),
    )
    return create_model("MealEstimate", dishes=(List[dish], ...), __base__=BaseModel)


def estimate_meal(transcript: str, ingredient_names: List[str], user_id: Optional[str] = None,
                  feature: str = FEATURE) -> Any:
    """The dishes in her transcript, each with its portion and ingredient
    grams. `ingredient_names` are the only names Claude may use."""
    names = tuple(sorted(set(ingredient_names)))
    response = client.beta.messages.parse(
        model=MEAL_MODEL,
        max_tokens=16000,
        system=MEAL_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                # The same list on every call: cached, so only the transcript is new.
                {
                    "type": "text",
                    "text": json.dumps({"ingredients": list(names)}, ensure_ascii=False),
                    "cache_control": {"type": "ephemeral"},
                },
                {"type": "text", "text": json.dumps({"transcript": transcript}, ensure_ascii=False)},
            ],
        }],
        output_format=meal_schema(names),
        # On a policy decline, the API re-runs the request on Anthropic's
        # recommended fallback model within the same call.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    # Billed even when it refuses, so recorded first.
    record_claude(response, feature, user_id=user_id)
    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise DietAgentRefusedError(f"Claude declined ({feature}, category: {category})")
    if response.parsed_output is None:
        raise ValueError(f"No structured output for {feature} (stop_reason={response.stop_reason})")
    return response.parsed_output
