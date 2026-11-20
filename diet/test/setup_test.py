import pytest

from diet.nutrition import TARGET_RANGES
from diet.setup import SetupError, assess, bmr_of, calculate_goals


def test_overweight_woman_gets_a_capped_deficit_worked_example():
    result = calculate_goals(158, 70, 50, "female", "lose")

    assert (result["bmi"], result["bmi_category"], result["recommended_goal"]) == (28.0, "overweight", "lose")
    # 700 + 987.5 - 250 - 161 = 1276.5; x 1.375 = 1755.
    assert (result["bmr"], result["tdee"]) == (1276, 1755)
    # 20% of 1755 (351) is less than 500; 1404 rounds to 1400.
    assert result["targets"] == {"energy_kcal": 1400, "protein_g": 75, "carbs_g": 187, "fat_g": 39, "fibre_g": 25}
    assert result["adjustment_kcal"] == 1400 - 1755


@pytest.mark.parametrize("height, weight, category, goal", [
    (165, 45, "underweight", "gain"),
    (165, 60, "healthy", "maintain"),
    (165, 80, "overweight", "lose"),
])
def test_bmi_category_decides_the_recommendation(height, weight, category, goal):
    result = assess(height, weight, 30, "female")
    assert (result["bmi_category"], result["recommended_goal"]) == (category, goal)


def test_maintain_is_maintenance_and_gain_adds_a_safe_surplus():
    maintain = calculate_goals(165, 60, 30, "female", "maintain")
    gain = calculate_goals(165, 60, 30, "female", "gain")
    assert maintain["targets"]["energy_kcal"] == round(maintain["tdee"] / 10) * 10
    assert gain["targets"]["energy_kcal"] - maintain["targets"]["energy_kcal"] == pytest.approx(300, abs=10)


def test_she_may_pick_a_goal_other_than_the_recommendation():
    result = calculate_goals(165, 60, 30, "female", "lose")
    assert result["recommended_goal"] == "maintain" and result["goal"] == "lose"
    assert result["targets"]["energy_kcal"] < round(result["tdee"])


def test_losing_weight_is_not_allowed_when_underweight():
    assert assess(165, 45, 30, "female")["allowed_goals"] == ["maintain", "gain"]
    with pytest.raises(SetupError):
        calculate_goals(165, 45, 30, "female", "lose")


def test_sex_constants():
    base = 10 * 60 + 6.25 * 160 - 5 * 30
    assert bmr_of(160, 60, 30, "male") == base + 5
    assert bmr_of(160, 60, 30, "female") == base - 161
    assert bmr_of(160, 60, 30, "other") == bmr_of(160, 60, 30, None) == base - 78


def test_a_deficit_never_goes_below_the_floor_or_bmr():
    small_older_woman = calculate_goals(145, 55, 80, "female", "lose")   # BMI 26.2, BMR ~ 856
    assert small_older_woman["targets"]["energy_kcal"] == 1200
    man = calculate_goals(160, 66, 85, "male", "lose")
    assert man["targets"]["energy_kcal"] >= max(1500, man["bmr"])


def test_protein_uses_a_healthy_reference_weight_when_overweight():
    heavy = calculate_goals(160, 110, 40, "female", "lose")
    assert heavy["targets"]["protein_g"] == round(1.2 * 24.9 * 1.6 ** 2)
    lean = calculate_goals(160, 55, 40, "female", "maintain")
    assert lean["targets"]["protein_g"] == round(1.2 * 55)


@pytest.mark.parametrize("height, weight, age, gender, goal", [
    (120, 30, 90, "female", "maintain"), (220, 200, 15, "male", "lose"), (220, 60, 15, "male", "gain"),
])
def test_targets_stay_in_range_at_the_extremes(height, weight, age, gender, goal):
    targets = calculate_goals(height, weight, age, gender, goal)["targets"]
    for key, value in targets.items():
        low, high = TARGET_RANGES[key]
        assert low <= value <= high
