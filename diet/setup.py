"""Her one-time diet setup (pure, no I/O): height, weight and age -> BMI
(which goal we recommend) and Mifflin-St Jeor (how many calories she needs)
-> her daily goals.

BMI = kg / m² decides the category. Mifflin-St Jeor gives the resting
energy need (BMR), times a lightly-active multiplier for maintenance. The
goal she confirms (or picks) adds a safe surplus, keeps maintenance, or takes
a safe deficit; protein, fat and fibre follow, and carbs fill the rest.
"""
from typing import Any, Dict, Optional, Tuple

from diet.nutrition import TARGET_RANGES

# What she can enter on the wheels.
INPUT_RANGES = {"height_cm": (120, 220), "weight_kg": (30, 200), "age": (15, 90)}

# WHO cut-offs (the Asian overweight cut-off would be 23).
UNDERWEIGHT_BELOW = 18.5
OVERWEIGHT_FROM = 25.0
# The weight protein is worked from is capped at this BMI's weight.
PROTEIN_REFERENCE_BMI = 24.9

ACTIVITY_MULTIPLIER = 1.375  # lightly active
GAIN_SURPLUS_KCAL = 300
LOSE_DEFICIT_KCAL = 500
LOSE_DEFICIT_MAX_SHARE = 0.20  # never more than 20% of maintenance
MIN_KCAL = {"male": 1500, "female": 1200}  # anyone else: the female floor

PROTEIN_G_PER_KG = 1.2
FAT_SHARE = 0.25
FIBRE_G_PER_1000_KCAL = 14
MIN_FIBRE_G = 25

# Mifflin-St Jeor's sex constant; the midpoint when it isn't male or female.
SEX_CONSTANT = {"male": 5, "female": -161}
OTHER_SEX_CONSTANT = -78

GOALS = ("lose", "maintain", "gain")
RECOMMENDED_GOAL = {"underweight": "gain", "healthy": "maintain", "overweight": "lose"}


class SetupError(ValueError):
    """A goal she isn't allowed (losing weight while underweight)."""


def bmi_of(height_cm: float, weight_kg: float) -> float:
    return round(weight_kg / (height_cm / 100) ** 2, 1)


def bmi_category(bmi: float) -> str:
    if bmi < UNDERWEIGHT_BELOW:
        return "underweight"
    return "overweight" if bmi >= OVERWEIGHT_FROM else "healthy"


def allowed_goals(category: str) -> Tuple[str, ...]:
    """Losing weight isn't offered to someone underweight."""
    return ("maintain", "gain") if category == "underweight" else GOALS


def bmr_of(height_cm: float, weight_kg: float, age: float, gender: Optional[str]) -> float:
    """Mifflin-St Jeor resting energy, kcal/day."""
    return 10 * weight_kg + 6.25 * height_cm - 5 * age + SEX_CONSTANT.get(gender or "", OTHER_SEX_CONSTANT)


def _clamp(key: str, value: float) -> int:
    low, high = TARGET_RANGES[key]
    return int(max(low, min(high, round(value))))


def assess(height_cm: float, weight_kg: float, age: float, gender: Optional[str]) -> Dict[str, Any]:
    """Her BMI, its category, the goal we recommend and the ones she may pick."""
    bmi = bmi_of(height_cm, weight_kg)
    category = bmi_category(bmi)
    bmr = bmr_of(height_cm, weight_kg, age, gender)
    return {
        "bmi": bmi,
        "bmi_category": category,
        "recommended_goal": RECOMMENDED_GOAL[category],
        "allowed_goals": list(allowed_goals(category)),
        "bmr": round(bmr),
        "tdee": round(bmr * ACTIVITY_MULTIPLIER),
    }


def calculate_goals(height_cm: float, weight_kg: float, age: float, gender: Optional[str],
                    goal: str) -> Dict[str, Any]:
    """`assess` plus her daily targets for `goal` (raises SetupError for a
    goal she isn't allowed)."""
    result = assess(height_cm, weight_kg, age, gender)
    if goal not in result["allowed_goals"]:
        raise SetupError(f"'{goal}' isn't an allowed goal here.")

    bmr = bmr_of(height_cm, weight_kg, age, gender)
    tdee = bmr * ACTIVITY_MULTIPLIER
    if goal == "gain":
        kcal = tdee + GAIN_SURPLUS_KCAL
    elif goal == "lose":
        kcal = tdee - min(LOSE_DEFICIT_KCAL, tdee * LOSE_DEFICIT_MAX_SHARE)
        kcal = max(kcal, bmr, MIN_KCAL.get(gender or "", MIN_KCAL["female"]))
    else:
        kcal = tdee
    kcal = round(kcal / 10) * 10
    energy = _clamp("energy_kcal", kcal)

    reference_kg = min(weight_kg, PROTEIN_REFERENCE_BMI * (height_cm / 100) ** 2)
    protein = _clamp("protein_g", PROTEIN_G_PER_KG * reference_kg)
    fat = _clamp("fat_g", energy * FAT_SHARE / 9)
    fibre = _clamp("fibre_g", max(MIN_FIBRE_G, energy / 1000 * FIBRE_G_PER_1000_KCAL))
    carbs = _clamp("carbs_g", (energy - protein * 4 - fat * 9) / 4)

    return {
        **result,
        "goal": goal,
        "activity_multiplier": ACTIVITY_MULTIPLIER,
        "adjustment_kcal": round(energy - tdee),
        "targets": {"energy_kcal": energy, "protein_g": protein, "carbs_g": carbs, "fat_g": fat,
                    "fibre_g": fibre},
    }
