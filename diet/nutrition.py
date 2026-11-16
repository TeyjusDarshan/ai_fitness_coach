"""The arithmetic of diet tracking (pure, no I/O): household units to grams,
recipes scaled to a portion, and nutrients summed from ingredients.

Nutrients live on ingredients only (per 100 g raw). A dish is a recipe —
raw grams of each ingredient per 100 g of the cooked dish — so a logged
item's nutrients are always the sum over its ingredient rows.
"""
import re
from typing import Any, Dict, Iterable, List, Optional

# Household measures a dish can have its own gram weight for.
PORTION_UNITS = (
    "piece", "karandi", "cup", "tumbler", "tablespoon", "teaspoon", "plate", "bowl", "handful", "slice",
)
# Spoken as a weight or volume: used as grams directly (1 ml taken as 1 g).
WEIGHT_UNITS = ("grams", "ml")
UNITS = PORTION_UNITS + WEIGHT_UNITS
MEALS = ("breakfast", "lunch", "dinner", "snack")

# Per 100 g on ingredients; the same keys in every totals dict.
MACROS = ("energy_kcal", "protein_g", "carbs_g", "fibre_g", "fat_g", "saturated_fat_g", "unsaturated_fat_g")
MICROS = (
    "sugar_g", "calcium_mg", "iron_mg", "sodium_mg", "potassium_mg", "magnesium_mg", "zinc_mg",
    "vitamin_a_mcg", "vitamin_c_mg", "vitamin_d_mcg", "vitamin_b12_mcg", "folate_mcg",
)
NUTRIENTS = MACROS + MICROS

DEFAULT_TARGETS = {"protein_g": 50, "fibre_g": 25}

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def name_key(name: str) -> str:
    """What makes two dish (or ingredient) names the same one: case,
    punctuation and spacing don't count ("Curd-Rice" = "curd rice")."""
    return _NON_ALNUM_RE.sub(" ", (name or "").casefold()).strip()


def portion_grams(quantity: float, unit: str, portions: Dict[str, float]) -> Optional[float]:
    """Grams of a dish for `quantity` of `unit`, given that dish's own unit
    weights. None when the dish has no weight for the unit."""
    if unit in WEIGHT_UNITS:
        return round(quantity, 1)
    per_unit = portions.get(unit)
    return round(quantity * float(per_unit), 1) if per_unit else None


def scale_recipe(recipe: Iterable[Dict[str, Any]], grams: float) -> List[Dict[str, Any]]:
    """A recipe ([{ingredient_id, grams_per_100g}]) as ingredient amounts for
    `grams` of the dish: [{ingredient_id, grams}]."""
    return [
        {"ingredient_id": row["ingredient_id"], "grams": round(float(row["grams_per_100g"]) * grams / 100, 2)}
        for row in recipe
    ]


def recipe_from_amounts(amounts: Iterable[Dict[str, Any]], grams: float) -> List[Dict[str, Any]]:
    """The reverse of scale_recipe: ingredient amounts of a `grams` portion
    back to a per-100 g recipe (her own version of a dish). Ingredients she
    removed (0 g) stay in, at 0, so they stay removed next time."""
    if not grams or grams <= 0:
        return []
    return [
        {"ingredient_id": row["ingredient_id"], "grams_per_100g": round(float(row["grams"]) * 100 / grams, 3)}
        for row in amounts
    ]


def empty_totals() -> Dict[str, float]:
    return {nutrient: 0.0 for nutrient in NUTRIENTS}


def nutrients_of(ingredient_rows: Iterable[Dict[str, Any]]) -> Dict[str, float]:
    """Nutrients of some ingredient amounts: each row has `grams` and its
    `ingredient` (per-100 g values; an unknown micronutrient counts as 0)."""
    totals = empty_totals()
    for row in ingredient_rows:
        ingredient = row.get("ingredient") or {}
        factor = float(row.get("grams") or 0) / 100
        for nutrient in NUTRIENTS:
            totals[nutrient] += float(ingredient.get(nutrient) or 0) * factor
    return totals


def add_totals(totals: Dict[str, float], more: Dict[str, float]) -> Dict[str, float]:
    for nutrient in NUTRIENTS:
        totals[nutrient] += more.get(nutrient) or 0
    return totals


def rounded(totals: Dict[str, float]) -> Dict[str, float]:
    return {nutrient: round(value, 1) for nutrient, value in totals.items()}


def targets_for(stored: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """Her daily targets: what the coach set, else the defaults."""
    stored = stored or {}
    return {key: stored.get(key) or default for key, default in DEFAULT_TARGETS.items()}
