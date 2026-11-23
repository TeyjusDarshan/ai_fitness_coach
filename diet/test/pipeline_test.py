from unittest.mock import MagicMock

import pytest

from diet import agent, pipeline
from diet.test.fakes import FakeRepo, dish, estimate

TRANSCRIPT = "kaalaila moonu idli, madhiyam rendu karandi sadam"
IDLI = dish("moonu idli", "Idli", 3, "piece", 120, [("Raw white rice", 45), ("Urad dal", 15)], meal="breakfast",
            name_ta="இட்லி")
RICE = dish("rendu karandi sadam", "Cooked Rice", 2, "karandi", 120,
            [("Raw white rice", 42), ("Sesame (gingelly) oil", 1.2)], meal="lunch")


@pytest.fixture
def repo():
    return FakeRepo()


@pytest.fixture
def claude(monkeypatch):
    call = MagicMock()
    monkeypatch.setattr(agent, "estimate_meal", call)
    return call


def _run(repo, log_id, transcript=TRANSCRIPT):
    pipeline.process_meal_log(repo, log_id, lambda log: transcript)
    return repo.logs[log_id], repo.log_items(log_id)


def _amounts(item):
    return {r["reference_id"]: r["grams"] for r in item["meal_log_item_ingredients"]}


def test_dishes_are_saved_with_ingredients_and_nutrients(repo, claude):
    claude.return_value = estimate(IDLI, RICE)

    log, items = _run(repo, repo.add_log())

    assert (log["status"], log["transcript"], log["model"]) == ("ready", TRANSCRIPT, agent.MEAL_MODEL)
    idli, rice = items
    assert (idli["dish_name"], idli["meal"], idli["portion_grams"], idli["needs_review"]) == ("Idli", "breakfast", 120, False)
    assert (idli["dish_name_ta"], rice["dish_name_ta"]) == ("இட்லி", None)
    assert _amounts(idli) == {1: 45, 3: 15}
    assert _amounts(rice) == {1: 42, 2: 1.2}
    # 45 g rice at 7 g + 15 g urad at 24 g protein per 100 g.
    assert round(idli["nutrients"]["protein_g"], 2) == 6.75
    assert round(rice["nutrients"]["fat_g"], 2) == 1.41
    assert rice["meal_log_item_ingredients"][1]["ingredient_name"] == "Sesame (gingelly) oil"


def test_claude_gets_only_the_transcript_and_each_name_once(repo, claude):
    claude.return_value = estimate(IDLI)

    _run(repo, repo.add_log("usr_7"))

    transcript, names, user_id = claude.call_args.args
    # "Raw white rice" is in two categories; it's offered (and stored) once, as the lowest id.
    assert (transcript, sorted(names), user_id) == (
        TRANSCRIPT, ["Raw white rice", "Sesame (gingelly) oil", "Urad dal"], "usr_7",
    )


def test_an_implausible_dish_is_kept_for_review(repo, claude):
    claude.return_value = estimate(dish("moonu idli", "Idli", 3, "piece", 120, [("Raw white rice", 900)]))

    log, [item] = _run(repo, repo.add_log())

    assert log["status"] == "ready"
    assert (item["needs_review"], item["meal_log_item_ingredients"], item["nutrients"]["energy_kcal"]) == (True, [], 0)


@pytest.mark.parametrize("transcript, proposed, error", [
    ("", None, "no_speech"),
    ("inniku workout nalla irundhuchu", estimate(), "no_food"),
    ("sambar saapten", estimate(dish("rendu vadai", "Vadai", 2, "piece", 80, [("Urad dal", 40)])), "no_food"),
])
def test_nothing_usable_fails_the_log(repo, claude, transcript, proposed, error):
    claude.return_value = proposed

    log, saved = _run(repo, repo.add_log(), transcript)

    assert (log["status"], log["error"], saved) == ("failed", error, [])


def test_a_skipped_meal_alone_is_a_ready_log_with_no_dishes(repo, claude):
    claude.return_value = estimate(skipped=["breakfast"])

    log, items = _run(repo, repo.add_log(), "inniku breakfast skip pannitten")

    assert (log["status"], log["error"], log["skipped_meals"], items) == ("ready", None, ["breakfast"], [])


def test_dishes_and_a_skipped_meal_are_both_kept(repo, claude):
    claude.return_value = estimate(RICE, skipped=["breakfast"])

    log, [item] = _run(repo, repo.add_log())

    assert (log["status"], log["skipped_meals"], item["dish_name"]) == ("ready", ["breakfast"], "Cooked Rice")


def test_skipped_meals_are_cleaned_up(repo, claude):
    claude.return_value = estimate(skipped=["dinner", "brunch", "breakfast", "dinner"])

    log, _ = _run(repo, repo.add_log(), "skip")

    assert log["skipped_meals"] == ["breakfast", "dinner"]


def test_a_crash_fails_the_log_and_a_processed_log_is_left_alone(repo, claude):
    claude.side_effect = RuntimeError("refused")
    log, _ = _run(repo, repo.add_log())
    assert (log["status"], log["error"]) == ("failed", "failed")

    done = repo.add_log(status="confirmed")
    pipeline.process_meal_log(repo, done, lambda log: pytest.fail("should not transcribe"))
    assert repo.logs[done]["status"] == "confirmed"


def test_a_log_discarded_while_processing_stays_discarded(repo, claude):
    log_id = repo.add_log()

    def estimate_meal(*args):
        repo.discard_meal_log(log_id)          # she taps Record again meanwhile
        return estimate(IDLI)

    claude.side_effect = estimate_meal
    log, _ = _run(repo, log_id)

    assert log["status"] == "discarded"


def test_the_output_schema_only_allows_the_given_names():
    schema = agent.meal_schema(("Raw white rice", "Urad dal")).model_json_schema()

    ingredient = next(d for name, d in schema["$defs"].items() if name.startswith("DishIngredient"))
    assert sorted(ingredient["properties"]["name"]["enum"]) == ["Raw white rice", "Urad dal"]


def test_the_output_schema_has_skipped_meals():
    schema = agent.meal_schema(("Raw white rice",)).model_json_schema()

    assert schema["properties"]["skipped_meals"]["items"]["enum"] == ["breakfast", "lunch", "dinner", "snack"]
