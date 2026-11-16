"""Checks on what Claude proposes before any of it is stored (pure, no I/O).

Claude only proposes: the items it heard, and for a dish nobody has logged
before, its recipe and the nutrients of any new ingredient. Anything that
can't be trusted is dropped or corrected here rather than saved.
"""
import re
from typing import Any, Dict, Iterable, List, Optional, Set

from diet.nutrition import MEALS, MICROS, PORTION_UNITS, UNITS, name_key

MAX_ITEMS = 40
MIN_QUANTITY, MAX_QUANTITY = 0.25, 20
MAX_GRAMS = 2000  # one item said in grams / ml

MIN_PORTION_GRAMS, MAX_PORTION_GRAMS = 1, 1000
MAX_RECIPE_INGREDIENTS = 25
MAX_INGREDIENT_PER_100G = 150
MIN_RECIPE_TOTAL, MAX_RECIPE_TOTAL = 15, 250
# How far Claude's energy may be from 4P + 4C + 9F before it's replaced.
ENERGY_TOLERANCE = 0.2

DISPLAY_UNITS = ("teaspoon", "tablespoon", "piece", "cup")

_PUNCTUATION_RE = re.compile(r"[^\w]+", re.UNICODE)


def _normalize(text: str) -> str:
    return _PUNCTUATION_RE.sub(" ", (text or "").casefold()).strip()


def quote_in_text(quote: str, text: str) -> bool:
    """Whether quote really occurs in text, ignoring case, punctuation and
    spacing — the guard against food she never mentioned."""
    normalized = _normalize(quote)
    return bool(normalized) and normalized in _normalize(text)


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def validate_items(items: Iterable[Any], transcript: str, food_ids: Set[int]) -> List[Dict[str, Any]]:
    """The parsed items worth keeping: each must quote what she said and
    name a food. A food_id that isn't in the catalogue is treated as a new
    dish; an unusable quantity falls back to one default serving."""
    kept: List[Dict[str, Any]] = []
    for item in items:
        name = (item.food_name or "").strip()
        if not name or not quote_in_text(item.quote, transcript):
            continue
        unit = item.unit if item.unit in UNITS else None
        quantity = _number(item.quantity)
        stated = bool(item.quantity_stated) and unit is not None and quantity is not None and quantity > 0
        if stated:
            limit = MAX_GRAMS if unit in ("grams", "ml") else MAX_QUANTITY
            floor = 1 if unit in ("grams", "ml") else MIN_QUANTITY
            quantity = min(max(quantity, floor), limit)
        kept.append({
            "food_id": item.food_id if item.food_id in food_ids else None,
            "food_name": name[:120],
            "quote": item.quote.strip(),
            "quantity": quantity if stated else None,
            "unit": unit if stated else None,
            "meal": item.meal if item.meal in MEALS else None,
        })
        if len(kept) == MAX_ITEMS:
            break
    return kept


def validate_ingredient(ingredient: Any) -> Optional[Dict[str, Any]]:
    """An ingredients row for a model-proposed ingredient (per 100 g raw),
    or None if its numbers can't be right."""
    name = (ingredient.name or "").strip()
    macros = {key: _number(getattr(ingredient, key)) for key in (
        "protein_g", "carbs_g", "fibre_g", "fat_g", "saturated_fat_g", "unsaturated_fat_g",
    )}
    if not name or any(value is None or value < 0 for value in macros.values()):
        return None
    protein, carbs, fat = macros["protein_g"], macros["carbs_g"], macros["fat_g"]
    if protein + carbs + fat > 100.5:
        return None
    if macros["fibre_g"] > carbs + 0.5:
        return None
    if macros["saturated_fat_g"] + macros["unsaturated_fat_g"] > fat + 0.5:
        return None

    from_macros = 4 * protein + 4 * carbs + 9 * fat
    energy = _number(ingredient.energy_kcal)
    if energy is None or energy < 0 or abs(energy - from_macros) > ENERGY_TOLERANCE * max(from_macros, 10):
        energy = from_macros

    row: Dict[str, Any] = {
        "name": name[:120], "name_key": name_key(name), "aliases": _aliases(ingredient.aliases, name),
        "energy_kcal": round(energy, 1), **{key: round(value, 2) for key, value in macros.items()},
    }
    for key in MICROS:
        value = _number(getattr(ingredient, key, None))
        row[key] = round(value, 3) if value is not None and value >= 0 else None

    per_unit = _number(ingredient.grams_per_display_unit)
    if ingredient.display_unit in DISPLAY_UNITS and per_unit and 0 < per_unit <= 500:
        row["display_unit"], row["grams_per_display_unit"] = ingredient.display_unit, round(per_unit, 1)
    else:
        row["display_unit"], row["grams_per_display_unit"] = None, None
    return row if row["name_key"] else None


def validate_portions(portions: Iterable[Any]) -> Dict[str, float]:
    """unit -> grams for the proposed unit weights that make sense."""
    kept: Dict[str, float] = {}
    for portion in portions:
        grams = _number(portion.grams)
        if portion.unit in PORTION_UNITS and grams and MIN_PORTION_GRAMS <= grams <= MAX_PORTION_GRAMS:
            kept.setdefault(portion.unit, round(grams, 1))
    return kept


def validate_dish(dish: Any, ingredient_ids: Dict[str, int]) -> Optional[Dict[str, Any]]:
    """A model-proposed dish as {name, name_key, aliases, default_unit,
    portions: {unit: grams}, recipe: [{ingredient_id, grams_per_100g}]}, or
    None if it can't be used. `ingredient_ids` maps every known ingredient's
    name_key to its id (catalogue plus the ones just added); the recipe may
    also name a catalogue ingredient by id."""
    name = (dish.name or "").strip()
    portions = validate_portions(dish.portions)
    if not name or not name_key(name) or not portions:
        return None
    default_unit = dish.default_unit if dish.default_unit in portions else next(iter(portions))

    known_ids = set(ingredient_ids.values())
    recipe: Dict[int, float] = {}
    for entry in dish.ingredients:
        grams = _number(entry.grams_per_100g)
        ingredient_id = entry.ingredient_id if entry.ingredient_id in known_ids else ingredient_ids.get(
            name_key(entry.name)
        )
        # One unusable line spoils the recipe: saving the rest would
        # silently lose that ingredient's nutrients.
        if ingredient_id is None or grams is None or not 0 < grams <= MAX_INGREDIENT_PER_100G:
            return None
        recipe[ingredient_id] = recipe.get(ingredient_id, 0) + grams
    total = sum(recipe.values())
    if not recipe or len(recipe) > MAX_RECIPE_INGREDIENTS or not MIN_RECIPE_TOTAL <= total <= MAX_RECIPE_TOTAL:
        return None

    return {
        "name": name[:120], "name_key": name_key(name), "aliases": _aliases(dish.aliases, name),
        "default_unit": default_unit, "portions": portions,
        "recipe": [
            {"ingredient_id": ingredient_id, "grams_per_100g": round(grams, 2)}
            for ingredient_id, grams in recipe.items()
        ],
    }


def _aliases(aliases: Optional[Iterable[str]], name: str) -> List[str]:
    seen = {name_key(name)}
    kept: List[str] = []
    for alias in aliases or []:
        alias = (alias or "").strip()
        key = _normalize(alias)
        if alias and key and key not in seen:
            seen.add(key)
            kept.append(alias[:80])
    return kept[:12]
