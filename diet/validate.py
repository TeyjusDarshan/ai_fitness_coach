"""Checks on what Claude proposes before any of it is stored (pure, no I/O).

Claude only proposes the dishes it heard and their ingredient amounts.
Anything that can't be trusted is dropped or flagged here rather than saved.
"""
import re
from typing import Any, Dict, Iterable, List, Optional

from diet.nutrition import MEALS, UNITS, WEIGHT_UNITS, name_key

MAX_ITEMS = 40
MIN_QUANTITY, MAX_QUANTITY = 0.25, 20
MAX_GRAMS = 2000  # one dish said in grams / ml, or one portion's weight
MAX_INGREDIENT_GRAMS = 1500
MAX_INGREDIENTS = 25
# Raw ingredients against the cooked portion: rice and dal swell, dry fries
# shrink, but outside this the estimate can't be right.
MIN_RAW_RATIO, MAX_RAW_RATIO = 0.15, 2.5

_PUNCTUATION_RE = re.compile(r"[^\w]+", re.UNICODE)
_TAMIL_RE = re.compile(r"[\u0B80-\u0BFF]")
MAX_NAME_TA = 80


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


def _ingredients(entries: Iterable[Any], reference_by_key: Dict[str, Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    """[{reference, grams}] with duplicates merged, or None if any line is
    unusable — saving the rest would silently lose that ingredient."""
    merged: Dict[int, Dict[str, Any]] = {}
    for entry in entries:
        reference = reference_by_key.get(name_key(getattr(entry, "name", "")))
        grams = _number(getattr(entry, "grams", None))
        if reference is None or grams is None or not 0 < grams <= MAX_INGREDIENT_GRAMS:
            return None
        line = merged.setdefault(reference["id"], {"reference": reference, "grams": 0.0})
        line["grams"] += grams
    lines = list(merged.values())
    return lines if 0 < len(lines) <= MAX_INGREDIENTS else None


def tamil_name(value: Optional[str]) -> Optional[str]:
    """The dish's Tamil-script name, or None when it isn't one (her screens
    then show the English name)."""
    value = (value or "").strip()
    return value if 0 < len(value) <= MAX_NAME_TA and _TAMIL_RE.search(value) else None


def validate_skipped(meals: Optional[Iterable[Any]]) -> List[str]:
    """The meals she said she skipped: known meal names only, each once, in
    day order (breakfast, lunch, dinner, snack)."""
    given = {str(meal) for meal in (meals or [])}
    return [meal for meal in MEALS if meal in given]


def validate_meal(dishes: Iterable[Any], transcript: str,
                  reference_by_key: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The proposed dishes worth keeping, as {dish_name, dish_name_ta, quote, meal,
    quantity, unit, assumed, portion_grams, needs_review, ingredients:
    [{reference, grams}]}. A dish must quote what she said and have a name;
    one whose ingredients or weight can't be right is kept for review with
    no ingredients. `reference_by_key` maps name_key(name) -> the canonical
    reference row."""
    kept: List[Dict[str, Any]] = []
    for dish in dishes:
        name = (dish.dish_name or "").strip()
        if not name or not quote_in_text(dish.quote, transcript):
            continue

        unit = dish.unit if dish.unit in UNITS else "piece"
        quantity = _number(dish.quantity)
        if quantity is None or quantity <= 0:
            quantity, assumed = 1.0, True
        else:
            assumed = not dish.quantity_stated
            low, high = (1, MAX_GRAMS) if unit in WEIGHT_UNITS else (MIN_QUANTITY, MAX_QUANTITY)
            quantity = min(max(quantity, low), high)

        portion = _number(dish.portion_grams)
        portion = round(portion, 1) if portion is not None and 1 <= portion <= MAX_GRAMS else None
        lines = _ingredients(dish.ingredients or [], reference_by_key) if portion else None
        if lines is not None:
            raw = sum(line["grams"] for line in lines)
            if not MIN_RAW_RATIO * portion <= raw <= MAX_RAW_RATIO * portion:
                lines = None

        kept.append({
            "dish_name": name[:120],
            "dish_name_ta": tamil_name(getattr(dish, "dish_name_ta", None)),
            "quote": dish.quote.strip(),
            "meal": dish.meal if dish.meal in MEALS else None,
            "quantity": round(quantity, 2),
            "unit": unit,
            "assumed": assumed,
            "portion_grams": portion,
            "needs_review": lines is None,
            "ingredients": [{**line, "grams": round(line["grams"], 2)} for line in lines or []],
        })
        if len(kept) == MAX_ITEMS:
            break
    return kept
