"""The arithmetic of diet tracking (pure, no I/O): nutrients summed from
ingredient amounts.

Nutrients live in `ingredient_nutrition_reference` (per 100 g, raw or as
sold). A logged dish is a list of ingredient amounts in grams for her
portion, so its nutrients are the sum over those amounts.
"""
import re
from typing import Any, Dict, Iterable, Optional, Tuple

# Household measures she might say, and amounts said as a weight or volume.
PORTION_UNITS = (
    "piece", "karandi", "cup", "tumbler", "tablespoon", "teaspoon", "plate", "bowl", "handful", "slice",
)
WEIGHT_UNITS = ("grams", "ml")
UNITS = PORTION_UNITS + WEIGHT_UNITS
MEALS = ("breakfast", "lunch", "dinner", "snack")

# The nutrient columns of ingredient_nutrition_reference (per 100 g); the
# same keys in every totals dict and in meal_log_items.nutrients.
MACROS = (
    "energy_kcal", "protein_g", "carbs_g", "sugar_g", "fibre_g", "soluble_fibre_g", "insoluble_fibre_g",
    "fat_g", "saturated_fat_g", "monounsaturated_fat_g", "polyunsaturated_fat_g", "unsaturated_fat_g",
    "trans_fat_g", "cholesterol_mg", "alcohol_g",
)
MICROS = (
    "sodium_mg", "potassium_mg", "calcium_mg", "iron_mg", "magnesium_mg", "phosphorus_mg", "zinc_mg",
    "vitamin_a_mcg_rae", "vitamin_c_mg", "vitamin_d_mcg", "vitamin_e_mg", "vitamin_k_mcg",
    "thiamin_b1_mg", "riboflavin_b2_mg", "niacin_b3_mg", "vitamin_b6_mg", "folate_mcg", "vitamin_b12_mcg",
)
NUTRIENTS = MACROS + MICROS

# Her daily goals when the coach hasn't set them (a moderately active woman
# aged 40-55), and the range a coach may set each to.
DEFAULT_TARGETS = {"energy_kcal": 1800, "protein_g": 50, "fibre_g": 25, "carbs_g": 225, "fat_g": 60}
TARGET_RANGES = {"energy_kcal": (500, 5000), "protein_g": (1, 500), "fibre_g": (1, 500), "carbs_g": (1, 1000),
                 "fat_g": (1, 500)}

# Ingredients a cook measures by the spoon, shown to her in teaspoons:
# reference category -> grams in one teaspoon.
_SPOON_CATEGORIES = {"oil_ghee": 5, "fat_additive": 5, "sweetener": 4, "sweetener_alt": 4, "salt": 6}
_SPOON_NAMES = {"salt": 6}

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def name_key(name: str) -> str:
    """What makes two names the same one: case, punctuation and spacing
    don't count ("Curd-Rice" = "curd rice")."""
    return _NON_ALNUM_RE.sub(" ", (name or "").casefold()).strip()


def display_unit(category: Optional[str], name: Optional[str]) -> Tuple[Optional[str], Optional[float]]:
    """("teaspoon", grams in one) for spoon-measured ingredients, else
    (None, None)."""
    grams = _SPOON_NAMES.get(name_key(name or "")) or _SPOON_CATEGORIES.get(category or "")
    return ("teaspoon", float(grams)) if grams else (None, None)


def empty_totals() -> Dict[str, float]:
    return {nutrient: 0.0 for nutrient in NUTRIENTS}


def nutrients_of(ingredient_rows: Iterable[Dict[str, Any]]) -> Dict[str, float]:
    """Nutrients of some ingredient amounts: each row has `grams` and its
    `reference` (per-100 g values; an unknown value counts as 0)."""
    totals = empty_totals()
    for row in ingredient_rows:
        reference = row.get("reference") or {}
        factor = float(row.get("grams") or 0) / 100
        for nutrient in NUTRIENTS:
            totals[nutrient] += float(reference.get(nutrient) or 0) * factor
    return totals


def add_totals(totals: Dict[str, float], more: Optional[Dict[str, Any]]) -> Dict[str, float]:
    for nutrient in NUTRIENTS:
        totals[nutrient] += float((more or {}).get(nutrient) or 0)
    return totals


def rounded(totals: Dict[str, float], digits: int = 1) -> Dict[str, float]:
    return {nutrient: round(float(value), digits) for nutrient, value in totals.items()}


def targets_for(stored: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """Her daily targets: what the coach set, else the defaults."""
    stored = stored or {}
    return {key: stored.get(key) or default for key, default in DEFAULT_TARGETS.items()}
