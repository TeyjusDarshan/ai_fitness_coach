"""New daily targets after a weekly decision (pure): the calorie number with
her floor and (gaining) ceiling applied, then the macros from her current
weight (diet.setup.macros_for)."""
from typing import Any, Dict, Optional

from diet.setup import ACTIVITY_MULTIPLIER, MIN_KCAL, bmr_of, macros_for

# Gaining: never more than this above maintenance.
GAIN_CEILING_OVER_MAINTENANCE = 500


def body(setup: Dict[str, Any], gender: Optional[str]) -> Dict[str, Any]:
    """What the formulas need from her diet setup."""
    return {"height_cm": float(setup["height_cm"]), "age": float(setup["age"]), "gender": gender}


def maintenance_kcal(weight_kg: float, person: Dict[str, Any]) -> float:
    return bmr_of(person["height_cm"], weight_kg, person["age"], person["gender"]) * ACTIVITY_MULTIPLIER


def floor_kcal(weight_kg: float, person: Dict[str, Any]) -> float:
    """Never below her BMR at her current weight, or 1200 kcal (1500 for men)."""
    bmr = bmr_of(person["height_cm"], weight_kg, person["age"], person["gender"])
    return max(bmr, MIN_KCAL.get(person["gender"] or "", MIN_KCAL["female"]))


def changed_targets(current_kcal: float, delta: int, goal: str, weight_kg: float,
                    person: Dict[str, Any]) -> Optional[Dict[str, int]]:
    """Her targets after `delta` kcal, or None when a cut can't go any lower
    (she's already at her floor)."""
    floor = floor_kcal(weight_kg, person)
    kcal = current_kcal + delta
    if delta < 0 and current_kcal <= floor + 5:
        return None
    kcal = max(kcal, floor)
    if goal == "gain":
        kcal = min(kcal, maintenance_kcal(weight_kg, person) + GAIN_CEILING_OVER_MAINTENANCE)
    return macros_for(kcal, weight_kg, person["height_cm"])


def maintenance_targets(weight_kg: float, person: Dict[str, Any]) -> Dict[str, int]:
    """Her targets for keeping this weight (target reached -> maintain)."""
    return macros_for(max(maintenance_kcal(weight_kg, person), floor_kcal(weight_kg, person)),
                      weight_kg, person["height_cm"])
