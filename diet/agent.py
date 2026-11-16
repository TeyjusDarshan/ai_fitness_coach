"""The two Claude calls of diet tracking, both structured output:

- parse_meal: her transcript + the catalogue of known dishes -> the items
  she ate (matched to a known dish, or named as a new one), on every log.
- estimate: for dishes nobody has logged before, their recipe, household
  unit weights and any new ingredients' nutrients — only on a miss, and on
  the stronger model since what it writes is reused for everyone.

Both only propose; diet/validate.py checks everything before it's stored.
"""
import json
import logging
import os
from typing import Any, Dict, List, Literal, Optional

import anthropic
from ai_usage import record_claude
from dotenv import load_dotenv
from pydantic import BaseModel

from diet.prompts import ESTIMATE_SYSTEM_PROMPT, PARSE_SYSTEM_PROMPT

load_dotenv()

logger = logging.getLogger(__name__)

PARSE_MODEL = "claude-sonnet-5-5"
ESTIMATE_MODEL = "claude-opus-5-5"
ESTIMATE_EFFORT = "medium"

client = anthropic.Anthropic(timeout=float(os.getenv("DIET_AGENT_TIMEOUT_SECONDS", "120")))

Unit = Literal[
    "piece", "karandi", "cup", "tumbler", "tablespoon", "teaspoon", "plate", "bowl", "handful", "slice",
    "grams", "ml",
]
PortionUnit = Literal[
    "piece", "karandi", "cup", "tumbler", "tablespoon", "teaspoon", "plate", "bowl", "handful", "slice",
]
Meal = Literal["breakfast", "lunch", "dinner", "snack"]


class ParsedItem(BaseModel):
    quote: str
    food_id: Optional[int]
    food_name: str
    quantity: float
    unit: Unit
    quantity_stated: bool
    meal: Optional[Meal]


class ParsedMeal(BaseModel):
    items: List[ParsedItem]


class Portion(BaseModel):
    unit: PortionUnit
    grams: float


class RecipeIngredient(BaseModel):
    ingredient_id: Optional[int]
    name: str
    grams_per_100g: float


class NewDish(BaseModel):
    name: str
    aliases: List[str]
    default_unit: PortionUnit
    portions: List[Portion]
    ingredients: List[RecipeIngredient]


class NewIngredient(BaseModel):
    name: str
    aliases: List[str]
    energy_kcal: float
    protein_g: float
    carbs_g: float
    fibre_g: float
    sugar_g: Optional[float]
    fat_g: float
    saturated_fat_g: float
    unsaturated_fat_g: float
    calcium_mg: Optional[float]
    iron_mg: Optional[float]
    sodium_mg: Optional[float]
    potassium_mg: Optional[float]
    magnesium_mg: Optional[float]
    zinc_mg: Optional[float]
    vitamin_a_mcg: Optional[float]
    vitamin_c_mg: Optional[float]
    vitamin_d_mcg: Optional[float]
    vitamin_b12_mcg: Optional[float]
    folate_mcg: Optional[float]
    display_unit: Optional[Literal["teaspoon", "tablespoon", "piece", "cup"]]
    grams_per_display_unit: Optional[float]


class ExistingDishPortion(BaseModel):
    food_id: int
    unit: PortionUnit
    grams: float


class Estimation(BaseModel):
    new_ingredients: List[NewIngredient]
    dishes: List[NewDish]
    portions_for_known_dishes: List[ExistingDishPortion]


class DietAgentRefusedError(RuntimeError):
    """Claude declined (and no fallback model took the request)."""


def _parse(model: str, system: str, payload: Dict[str, Any], output_format, feature: str,
           user_id: Optional[str], **extra):
    user_content = json.dumps(payload, indent=2, default=str, ensure_ascii=False)
    response = client.beta.messages.parse(
        model=model,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user_content}],
        output_format=output_format,
        # On a policy decline, the API re-runs the request on Anthropic's
        # recommended fallback model within the same call.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        **extra,
    )
    # Billed even when it refuses, so recorded first.
    record_claude(response, feature, user_id=user_id)
    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise DietAgentRefusedError(f"Claude declined ({feature}, category: {category})")
    if response.parsed_output is None:
        raise ValueError(f"No structured output for {feature} (stop_reason={response.stop_reason})")
    return response.parsed_output


def parse_meal(transcript: str, foods: List[Dict[str, Any]], user_id: Optional[str] = None) -> ParsedMeal:
    """What she ate, from her transcript. `foods` is the catalogue of known
    dishes ([{id, name, aliases}]) to match against."""
    return _parse(
        PARSE_MODEL, PARSE_SYSTEM_PROMPT, {"transcript": transcript, "foods": foods},
        ParsedMeal, "meal_parsing", user_id,
    )


def estimate(
    new_dishes: List[str],
    missing_portions: List[Dict[str, Any]],
    ingredients: List[Dict[str, Any]],
    user_id: Optional[str] = None,
) -> Estimation:
    """Recipes, unit weights and new ingredients for dishes not yet in the
    table, plus a missing unit weight for dishes that are. `ingredients` is
    the catalogue of known ingredients ([{id, name}])."""
    return _parse(
        ESTIMATE_MODEL, ESTIMATE_SYSTEM_PROMPT,
        {"new_dishes": new_dishes, "missing_portions": missing_portions, "ingredients": ingredients},
        Estimation, "recipe_estimation", user_id,
        output_config={"effort": ESTIMATE_EFFORT},
    )
