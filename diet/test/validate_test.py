from diet.nutrition import name_key, nutrients_of, portion_grams, recipe_from_amounts, scale_recipe
from diet.test.fakes import new_dish, new_ingredient, parsed
from diet.validate import quote_in_text, validate_dish, validate_ingredient, validate_items

TRANSCRIPT = "kaalaila moonu idli, oru karandi sambar saapten"


def test_items_must_quote_what_she_said():
    items = validate_items(parsed(
        ("moonu idli", 1, "Idli", 3, "piece"),
        ("rendu vadai", None, "Vadai", 2, "piece"),          # never said
    ).items, TRANSCRIPT, {1})

    assert [(i["food_id"], i["food_name"], i["quantity"], i["unit"]) for i in items] == [(1, "Idli", 3, "piece")]


def test_unknown_food_id_becomes_a_new_dish_and_no_amount_is_left_open():
    items = validate_items(parsed(
        ("oru karandi sambar", 99, "Sambar", 1, "karandi"),
        ("Moonu IDLI,", None, "Idli", 1, "piece", False),
    ).items, TRANSCRIPT, {1})

    assert items[0]["food_id"] is None
    assert (items[1]["quantity"], items[1]["unit"]) == (None, None)


def test_quantities_are_kept_in_range():
    items = validate_items(parsed(
        ("moonu idli", 1, "Idli", 300, "piece"),
        ("oru karandi sambar", None, "Sambar", 5000, "grams"),
    ).items, TRANSCRIPT, {1})

    assert [i["quantity"] for i in items] == [20, 2000]


def test_quote_check_ignores_case_and_punctuation():
    assert quote_in_text("ஒரு டம்ளர் காபி", "காலையில, ஒரு  டம்ளர் காபி!")
    assert not quote_in_text("", "anything")


def test_ingredient_with_impossible_macros_is_dropped():
    assert validate_ingredient(new_ingredient("Magic", protein=60, carbs=50, fat=10)) is None
    assert validate_ingredient(new_ingredient("Odd Fat", fat=5, saturated_fat_g=4, unsaturated_fat_g=4)) is None
    assert validate_ingredient(new_ingredient("Odd Fibre", carbs=2, fibre_g=9)) is None


def test_ingredient_energy_is_recomputed_when_far_off():
    row = validate_ingredient(new_ingredient("Toor Dal", protein=22, carbs=60, fat=1.5, energy_kcal=900))

    assert row["energy_kcal"] == 4 * 22 + 4 * 60 + 9 * 1.5
    assert row["name_key"] == "toor dal"
    assert row["calcium_mg"] is None


def test_ingredient_display_unit_needs_a_weight():
    with_unit = validate_ingredient(new_ingredient("Ghee", protein=0, carbs=0, fat=99, fibre_g=0, display_unit="teaspoon", grams_per_display_unit=5))
    without = validate_ingredient(new_ingredient("Ghee", protein=0, carbs=0, fat=99, fibre_g=0, display_unit="teaspoon"))

    assert (with_unit["display_unit"], with_unit["grams_per_display_unit"]) == ("teaspoon", 5)
    assert without["display_unit"] is None


def test_dish_recipe_resolves_ingredients_by_id_or_name():
    dish = validate_dish(new_dish(
        "Sambar", {"karandi": 50, "cup": 150, "piece": 5000},
        [(1, "Raw Rice", 10), (None, "Toor Dal", 6), (None, "toor  dal", 2)], default_unit="plate",
    ), {"raw rice": 1, "toor dal": 7})

    assert dish["portions"] == {"karandi": 50, "cup": 150}        # the absurd weight is left out
    assert dish["default_unit"] == "karandi"                      # "plate" has no weight
    assert dish["recipe"] == [{"ingredient_id": 1, "grams_per_100g": 10}, {"ingredient_id": 7, "grams_per_100g": 8}]


def test_dish_with_an_unknown_ingredient_or_absurd_total_is_dropped():
    known = {"raw rice": 1}
    assert validate_dish(new_dish("X", {"cup": 100}, [(None, "Unicorn", 10), (1, "Raw Rice", 30)]), known) is None
    assert validate_dish(new_dish("X", {"cup": 100}, [(1, "Raw Rice", 2)]), known) is None
    assert validate_dish(new_dish("X", {}, [(1, "Raw Rice", 30)]), known) is None


def test_nutrition_maths():
    assert name_key(" Curd-Rice ") == "curd rice"
    assert portion_grams(2, "karandi", {"karandi": 60}) == 120
    assert portion_grams(150, "ml", {}) == 150
    assert portion_grams(1, "plate", {"karandi": 60}) is None

    amounts = scale_recipe([{"ingredient_id": 1, "grams_per_100g": 35}], 120)
    assert amounts == [{"ingredient_id": 1, "grams": 42}]
    assert recipe_from_amounts(amounts, 120) == [{"ingredient_id": 1, "grams_per_100g": 35}]

    totals = nutrients_of([{"grams": 42, "ingredient": {"protein_g": 7, "calcium_mg": None}}])
    assert round(totals["protein_g"], 2) == 2.94 and totals["calcium_mg"] == 0
