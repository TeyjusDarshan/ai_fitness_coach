from diet.nutrition import display_unit, name_key, nutrients_of
from diet.test.fakes import OIL, RICE, URAD, dish
from diet.validate import quote_in_text, validate_meal

TRANSCRIPT = "kaalaila moonu idli, oru karandi sadam saapten"
BY_KEY = {name_key(row["name"]): row for row in (RICE, OIL, URAD)}
IDLI = [("Raw white rice", 45), ("Urad dal", 15)]


def _validate(*dishes):
    return validate_meal(list(dishes), TRANSCRIPT, BY_KEY)


def test_a_dish_keeps_its_ingredient_lines_with_their_reference_rows():
    [kept] = _validate(dish("moonu idli", "Idli", 3, "piece", 120, IDLI, meal="breakfast"))

    assert (kept["dish_name"], kept["quantity"], kept["unit"], kept["meal"]) == ("Idli", 3, "piece", "breakfast")
    assert (kept["portion_grams"], kept["assumed"], kept["needs_review"]) == (120, False, False)
    assert [(line["reference"]["id"], line["grams"]) for line in kept["ingredients"]] == [(1, 45), (3, 15)]


def test_dishes_must_quote_what_she_said():
    kept = _validate(
        dish("moonu idli", "Idli", 3, "piece", 120, IDLI),
        dish("rendu vadai", "Vadai", 2, "piece", 80, [("Urad dal", 40)]),     # never said
        dish("oru karandi sadam", "", 1, "karandi", 60, [("Raw white rice", 21)]),  # no name
    )

    assert [d["dish_name"] for d in kept] == ["Idli"]


def test_duplicate_ingredients_are_merged_and_names_match_loosely():
    [kept] = _validate(dish("oru karandi sadam", "Rice", 1, "karandi", 60, [
        ("Raw white rice", 15), ("raw  WHITE rice", 6), ("Sesame (gingelly) oil", 1),
    ]))

    assert [(line["reference"]["id"], line["grams"]) for line in kept["ingredients"]] == [(1, 21), (2, 1)]


def test_an_implausible_estimate_is_kept_for_review_without_ingredients():
    kept = _validate(
        dish("moonu idli", "Idli", 3, "piece", 120, [("Raw white rice", 900)]),         # far too much raw food
        dish("moonu idli", "Idli", 3, "piece", 120, [("Unicorn", 30), ("Urad dal", 10)]),  # unknown name
        dish("moonu idli", "Idli", 3, "piece", 0, IDLI),                                # no weight
        dish("moonu idli", "Idli", 3, "piece", 120, []),                                # no ingredients
    )

    assert [(d["needs_review"], d["ingredients"]) for d in kept] == [(True, [])] * 4


def test_a_watery_dish_keeps_its_ingredients_however_light_they_are():
    """Water is left out of the ingredients, so ragi koozh (about 20 g of
    flour in a 200 g cup) or a shake (30 g of whey in water) weighs a small
    fraction of the portion. Meal log 28 (2026-11-26) lost its koozh to the
    old 0.15x floor."""
    kept = _validate(
        dish("oru karandi sadam", "Kanji", 1, "karandi", 200, [("Raw white rice", 20), ("Sesame (gingelly) oil", 1)]),
        dish("oru karandi sadam", "Thin kanji", 1, "karandi", 300, [("Raw white rice", 2)]),
    )

    assert [d["needs_review"] for d in kept] == [False, False]
    assert [sum(line["grams"] for line in d["ingredients"]) for d in kept] == [21, 2]


def test_ingredients_over_two_and_a_half_times_the_portion_are_still_flagged():
    kept = _validate(
        dish("oru karandi sadam", "Rice", 1, "karandi", 60, [("Raw white rice", 150)]),   # exactly 2.5x
        dish("oru karandi sadam", "Rice", 1, "karandi", 60, [("Raw white rice", 151)]),   # a whole pot's worth
    )

    assert [d["needs_review"] for d in kept] == [False, True]


def test_quantities_are_kept_in_range_and_a_missing_amount_is_assumed():
    kept = _validate(
        dish("moonu idli", "Idli", 300, "piece", 120, IDLI),
        dish("oru karandi sadam", "Rice", 5000, "grams", 60, [("Raw white rice", 21)]),
        dish("Moonu IDLI,", "Idli", 1, "piece", 40, [("Raw white rice", 15)], stated=False),
    )

    assert [d["quantity"] for d in kept] == [20, 2000, 1]
    assert [d["assumed"] for d in kept] == [False, False, True]


def test_quote_check_ignores_case_and_punctuation():
    assert quote_in_text("ஒரு டம்ளர் காபி", "காலையில, ஒரு  டம்ளர் காபி!")
    assert not quote_in_text("", "anything")


def test_nutrition_maths():
    assert name_key(" Curd-Rice ") == "curd rice"
    totals = nutrients_of([{"grams": 42, "reference": {"protein_g": 7, "calcium_mg": None}}])
    assert round(totals["protein_g"], 2) == 2.94 and totals["calcium_mg"] == 0
    assert display_unit("oil_ghee", "Ghee") == ("teaspoon", 5.0)
    assert display_unit("spice", "Salt") == ("teaspoon", 6.0)
    assert display_unit("carb", "Raw white rice") == (None, None)


def test_the_tamil_dish_name_is_kept_only_when_it_is_tamil_script():
    kept = _validate(
        dish("moonu idli", "Idli", 3, "piece", 120, IDLI, name_ta=" இட்லி "),
        dish("moonu idli", "Idli", 3, "piece", 120, IDLI, name_ta="Idli"),
        dish("moonu idli", "Idli", 3, "piece", 120, IDLI, name_ta=""),
        dish("moonu idli", "Idli", 3, "piece", 120, IDLI),
    )

    assert [d["dish_name_ta"] for d in kept] == ["இட்லி", None, None, None]
