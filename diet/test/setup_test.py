from datetime import date

import pytest

from diet.nutrition import TARGET_RANGES
from diet.setup import SetupError, assess, bmr_of, calculate_goals

TODAY = date(2026, 11, 20)


def test_overweight_woman_gets_a_capped_deficit_and_a_timeline_worked_example():
    result = calculate_goals(158, 70, 50, "female", "lose", 63, today=TODAY)

    assert (result["bmi"], result["bmi_category"], result["recommended_goal"]) == (28.0, "overweight", "lose")
    # 700 + 987.5 - 250 - 161 = 1276.5; x 1.375 = 1755.
    assert (result["bmr"], result["tdee"]) == (1276, 1755)
    # 20% of 1755 (351) is less than 500; 1404 rounds to 1400.
    assert result["targets"] == {"energy_kcal": 1400, "protein_g": 75, "carbs_g": 187, "fat_g": 39, "fibre_g": 25}
    # 355 kcal a day ~ 0.32 kg a week: 7 kg takes 22 weeks.
    assert (result["target_weight_kg"], result["weekly_change_kg"], result["weeks"]) == (63, 0.3, 22)
    assert result["target_date"] == "2027-04-23"


@pytest.mark.parametrize("height, weight, category, goal, allowed", [
    (165, 45, "underweight", "gain", ["maintain", "gain"]),
    (165, 60, "healthy", "maintain", ["lose", "maintain", "gain"]),
    (165, 80, "overweight", "lose", ["lose", "maintain"]),
])
def test_bmi_category_decides_the_recommendation_and_the_choices(height, weight, category, goal, allowed):
    result = assess(height, weight, 30, "female")
    assert (result["bmi_category"], result["recommended_goal"], result["allowed_goals"]) == (category, goal, allowed)


def test_unsafe_goals_are_refused():
    with pytest.raises(SetupError):
        calculate_goals(165, 45, 30, "female", "lose", 44)   # underweight
    with pytest.raises(SetupError):
        calculate_goals(165, 80, 30, "female", "gain", 81)   # overweight


def test_goals_disappear_at_the_edges_of_the_healthy_range():
    assert assess(165, 51, 30, "female")["allowed_goals"] == ["maintain", "gain"]   # BMI 18.7: no room to lose
    assert assess(165, 67, 30, "female")["allowed_goals"] == ["lose", "maintain"]   # BMI 24.6: no room to gain


def test_suggested_targets_are_a_first_step_towards_a_healthy_bmi():
    # Overweight: 10% down, but not below the BMI 24.9 weight (62.2 kg at 158 cm).
    assert assess(158, 70, 50, "female")["target_weights"] == {"lose": {"min": 47, "max": 69, "suggested": 63}}
    assert assess(160, 110, 40, "female")["target_weights"]["lose"]["suggested"] == 99
    # Underweight: up to the BMI 18.5 weight, at most 5 kg at a time.
    assert assess(165, 45, 30, "female")["target_weights"] == {"gain": {"min": 46, "max": 67, "suggested": 50}}
    # Healthy: 10% down or 3 kg up.
    assert assess(165, 60, 30, "female")["target_weights"] == {
        "lose": {"min": 51, "max": 59, "suggested": 54},
        "gain": {"min": 61, "max": 67, "suggested": 63},
    }


def test_a_target_weight_is_needed_and_must_be_in_range_for_losing_or_gaining():
    for target in (None, 50, 60):
        with pytest.raises(SetupError):
            calculate_goals(165, 60, 30, "female", "lose", target)
    maintain = calculate_goals(165, 60, 30, "female", "maintain", 40)
    assert (maintain["target_weight_kg"], maintain["weeks"], maintain["target_date"]) == (None, None, None)


def test_healthy_woman_losing_weight_gets_the_gentler_deficit():
    result = calculate_goals(165, 60, 30, "female", "lose", 57, today=TODAY)
    assert result["recommended_goal"] == "maintain" and result["tdee"] == 1815
    # min(250, 10% of 1815) = 182 -> 1633 -> 1630.
    assert result["targets"]["energy_kcal"] == 1630
    assert (result["weekly_change_kg"], result["weeks"]) == (0.2, 18)


def test_gaining_adds_a_safe_surplus():
    maintain = calculate_goals(165, 60, 30, "female", "maintain")
    gain = calculate_goals(165, 60, 30, "female", "gain", 63, today=TODAY)
    assert maintain["targets"]["energy_kcal"] == round(maintain["tdee"] / 10) * 10
    assert gain["targets"]["energy_kcal"] - maintain["targets"]["energy_kcal"] == pytest.approx(300, abs=10)
    assert (gain["weekly_change_kg"], gain["weeks"]) == (0.3, 11)


def test_no_timeline_when_the_floors_leave_too_little_room():
    small_older_woman = calculate_goals(145, 55, 80, "female", "lose", 52, today=TODAY)   # BMI 26.2
    assert small_older_woman["targets"]["energy_kcal"] == 1200
    assert (small_older_woman["target_weight_kg"], small_older_woman["weeks"]) == (52, None)
    assert small_older_woman["target_date"] is None


def test_sex_constants():
    base = 10 * 60 + 6.25 * 160 - 5 * 30
    assert bmr_of(160, 60, 30, "male") == base + 5
    assert bmr_of(160, 60, 30, "female") == base - 161
    assert bmr_of(160, 60, 30, "other") == bmr_of(160, 60, 30, None) == base - 78


def test_a_deficit_never_goes_below_the_floor_or_bmr():
    man = calculate_goals(160, 66, 85, "male", "lose", 60)
    assert man["targets"]["energy_kcal"] >= max(1500, man["bmr"])


def test_protein_uses_a_healthy_reference_weight_when_overweight():
    heavy = calculate_goals(160, 110, 40, "female", "lose", 99)
    assert heavy["targets"]["protein_g"] == round(1.2 * 24.9 * 1.6 ** 2)
    lean = calculate_goals(160, 55, 40, "female", "maintain")
    assert lean["targets"]["protein_g"] == round(1.2 * 55)


@pytest.mark.parametrize("height, weight, age, gender, goal, target", [
    (120, 30, 90, "female", "maintain", None), (220, 200, 15, "male", "lose", 150), (220, 60, 15, "male", "gain", 65),
])
def test_targets_stay_in_range_at_the_extremes(height, weight, age, gender, goal, target):
    targets = calculate_goals(height, weight, age, gender, goal, target)["targets"]
    for key, value in targets.items():
        low, high = TARGET_RANGES[key]
        assert low <= value <= high
