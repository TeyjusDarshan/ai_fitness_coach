"""Her one-time diet setup (pure, no I/O): height, weight and age -> BMI
(which goal we recommend) and Mifflin-St Jeor (how many calories she needs)
-> her daily goals, her target weight and how long it should take.

BMI = kg / m² decides the category and which goals she may pick. Mifflin-St
Jeor gives the resting energy need (BMR), times a lightly-active multiplier
for maintenance. The goal she confirms (or picks) adds a safe surplus, keeps
maintenance, or takes a safe deficit; protein, fat and fibre follow, and carbs
fill the rest. For losing or gaining she sets a target weight (we suggest a
first, reachable step towards a healthy BMI), and the timeline follows from
her calorie change (7700 kcal ≈ 1 kg).
"""
import math
from datetime import date, timedelta
from typing import Any, Dict, Optional

from diet.nutrition import TARGET_RANGES

# What she can enter on the wheels.
INPUT_RANGES = {"height_cm": (120, 220), "weight_kg": (30, 200), "age": (15, 90)}

# WHO cut-offs (the Asian overweight cut-off would be 23).
UNDERWEIGHT_BELOW = 18.5
OVERWEIGHT_FROM = 25.0
# The top of the healthy range: protein is worked from this weight at most,
# and no one is helped to gain past it.
HEALTHY_TOP_BMI = 24.9

ACTIVITY_MULTIPLIER = 1.375  # lightly active
GAIN_SURPLUS_KCAL = 300
# Losing weight: (most kcal, most share of maintenance) per BMI category. A
# woman already at a healthy weight gets the gentler deficit.
LOSE_DEFICIT = {"overweight": (500, 0.20), "healthy": (250, 0.10)}
MIN_KCAL = {"male": 1500, "female": 1200}  # anyone else: the female floor

PROTEIN_G_PER_KG = 1.2
FAT_SHARE = 0.25
FIBRE_G_PER_1000_KCAL = 14
MIN_FIBRE_G = 25

# Suggested targets: a first step, not the whole way.
LOSE_STEP_SHARE = 0.10   # 10% of her weight
GAIN_STEP_KG = 3         # healthy and wanting to gain
MAX_GAIN_STEP_KG = 5     # underweight: up to a healthy BMI, at most this much
KCAL_PER_KG = 7700
# Below this daily change (the calorie floors can leave little room) there
# is no honest date to promise.
MIN_TIMELINE_KCAL = 100

# Mifflin-St Jeor's sex constant; the midpoint when it isn't male or female.
SEX_CONSTANT = {"male": 5, "female": -161}
OTHER_SEX_CONSTANT = -78

GOALS = ("lose", "maintain", "gain")
RECOMMENDED_GOAL = {"underweight": "gain", "healthy": "maintain", "overweight": "lose"}


class SetupError(ValueError):
    """A goal or target weight she isn't allowed."""


def bmi_of(height_cm: float, weight_kg: float) -> float:
    return round(weight_kg / (height_cm / 100) ** 2, 1)


def weight_at(bmi: float, height_cm: float) -> float:
    """The weight that gives this BMI at her height."""
    return bmi * (height_cm / 100) ** 2


def bmi_category(bmi: float) -> str:
    if bmi < UNDERWEIGHT_BELOW:
        return "underweight"
    return "overweight" if bmi >= OVERWEIGHT_FROM else "healthy"


def bmr_of(height_cm: float, weight_kg: float, age: float, gender: Optional[str]) -> float:
    """Mifflin-St Jeor resting energy, kcal/day."""
    return 10 * weight_kg + 6.25 * height_cm - 5 * age + SEX_CONSTANT.get(gender or "", OTHER_SEX_CONSTANT)


def _within(value: float, low: int, high: int) -> int:
    return int(max(low, min(high, round(value))))


def target_weights(height_cm: float, weight_kg: float, category: str) -> Dict[str, Dict[str, int]]:
    """For losing and gaining, the target weights she may pick (whole kg,
    staying within a healthy BMI) and the one we suggest. A goal with no
    possible target isn't offered: an underweight woman can't lose, an
    overweight one can't gain."""
    result = {}
    lose_min, lose_max = math.ceil(weight_at(UNDERWEIGHT_BELOW, height_cm)), math.ceil(weight_kg) - 1
    if lose_min <= lose_max:
        suggested = weight_kg * (1 - LOSE_STEP_SHARE)
        if category == "overweight":
            suggested = max(suggested, weight_at(HEALTHY_TOP_BMI, height_cm))
        result["lose"] = {"min": lose_min, "max": lose_max, "suggested": _within(suggested, lose_min, lose_max)}

    gain_min, gain_max = math.floor(weight_kg) + 1, math.floor(weight_at(HEALTHY_TOP_BMI, height_cm))
    if gain_min <= gain_max:
        if category == "underweight":
            suggested = min(math.ceil(weight_at(UNDERWEIGHT_BELOW, height_cm)), weight_kg + MAX_GAIN_STEP_KG)
        else:
            suggested = weight_kg + GAIN_STEP_KG
        result["gain"] = {"min": gain_min, "max": gain_max, "suggested": _within(suggested, gain_min, gain_max)}
    return result


def _clamp(key: str, value: float) -> int:
    low, high = TARGET_RANGES[key]
    return int(max(low, min(high, round(value))))


def assess(height_cm: float, weight_kg: float, age: float, gender: Optional[str]) -> Dict[str, Any]:
    """Her BMI, its category, the goal we recommend, the goals she may pick
    and, for losing / gaining, the target weights on offer."""
    bmi = bmi_of(height_cm, weight_kg)
    category = bmi_category(bmi)
    bmr = bmr_of(height_cm, weight_kg, age, gender)
    targets = target_weights(height_cm, weight_kg, category)
    return {
        "bmi": bmi,
        "bmi_category": category,
        "recommended_goal": RECOMMENDED_GOAL[category],
        "allowed_goals": [goal for goal in GOALS if goal == "maintain" or goal in targets],
        "target_weights": targets,
        "bmr": round(bmr),
        "tdee": round(bmr * ACTIVITY_MULTIPLIER),
    }


def calculate_goals(height_cm: float, weight_kg: float, age: float, gender: Optional[str], goal: str,
                    target_weight_kg: Optional[float] = None, today: Optional[date] = None) -> Dict[str, Any]:
    """`assess` plus her daily targets for `goal` and, for losing or gaining,
    her target weight and the timeline to it. Raises SetupError for a goal
    she isn't allowed or a missing / out-of-range target weight."""
    result = assess(height_cm, weight_kg, age, gender)
    if goal not in result["allowed_goals"]:
        raise SetupError(f"'{goal}' isn't an allowed goal here.")
    target = None
    if goal != "maintain":
        bounds = result["target_weights"][goal]
        if target_weight_kg is None or not bounds["min"] <= target_weight_kg <= bounds["max"]:
            raise SetupError(f"'target_weight_kg' must be between {bounds['min']} and {bounds['max']}.")
        target = round(float(target_weight_kg), 1)

    bmr = bmr_of(height_cm, weight_kg, age, gender)
    tdee = bmr * ACTIVITY_MULTIPLIER
    if goal == "gain":
        kcal = tdee + GAIN_SURPLUS_KCAL
    elif goal == "lose":
        most_kcal, most_share = LOSE_DEFICIT[result["bmi_category"]]
        kcal = tdee - min(most_kcal, tdee * most_share)
        kcal = max(kcal, bmr, MIN_KCAL.get(gender or "", MIN_KCAL["female"]))
    else:
        kcal = tdee
    kcal = round(kcal / 10) * 10
    energy = _clamp("energy_kcal", kcal)

    reference_kg = min(weight_kg, weight_at(HEALTHY_TOP_BMI, height_cm))
    protein = _clamp("protein_g", PROTEIN_G_PER_KG * reference_kg)
    fat = _clamp("fat_g", energy * FAT_SHARE / 9)
    fibre = _clamp("fibre_g", max(MIN_FIBRE_G, energy / 1000 * FIBRE_G_PER_1000_KCAL))
    carbs = _clamp("carbs_g", (energy - protein * 4 - fat * 9) / 4)

    weekly = weeks = target_date = None
    change_kcal = abs(energy - tdee)
    if target is not None and change_kcal >= MIN_TIMELINE_KCAL:
        weekly_kg = change_kcal * 7 / KCAL_PER_KG
        weeks = math.ceil(abs(weight_kg - target) / weekly_kg)
        weekly = round(weekly_kg, 1)
        target_date = ((today or date.today()) + timedelta(weeks=weeks)).isoformat()

    return {
        **result,
        "goal": goal,
        "activity_multiplier": ACTIVITY_MULTIPLIER,
        "adjustment_kcal": round(energy - tdee),
        "target_weight_kg": target,
        "weekly_change_kg": weekly,
        "weeks": weeks,
        "target_date": target_date,
        "targets": {"energy_kcal": energy, "protein_g": protein, "carbs_g": carbs, "fat_g": fat,
                    "fibre_g": fibre},
    }
