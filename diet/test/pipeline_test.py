from unittest.mock import MagicMock

import pytest

from diet import agent, pipeline
from diet.test.fakes import FakeRepo, estimation, new_dish, new_ingredient, parsed

TRANSCRIPT = "moonu idli, oru karandi sadam, oru plate sadam"


@pytest.fixture
def repo():
    return FakeRepo()


@pytest.fixture
def claude(monkeypatch):
    calls = MagicMock()
    monkeypatch.setattr(agent, "parse_meal", calls.parse_meal)
    monkeypatch.setattr(agent, "estimate", calls.estimate)
    return calls


def _run(repo, log_id, transcript=TRANSCRIPT):
    pipeline.process_meal_log(repo, log_id, lambda log: transcript)
    return repo.logs[log_id], repo.log_items(log_id)


def test_known_dish_is_fetched_from_the_table_without_estimating(repo, claude):
    rice = repo.add_food("Cooked Rice", {"karandi": 60}, {1: 35, 2: 1})
    claude.parse_meal.return_value = parsed(("oru karandi sadam", rice, "Cooked Rice", 2, "karandi", True, "lunch"))

    log, items = _run(repo, repo.add_log())

    claude.estimate.assert_not_called()
    assert (log["status"], log["transcript"]) == ("ready", TRANSCRIPT)
    item = items[0]
    assert (item["food_id"], item["grams"], item["meal"], item["assumed"]) == (rice, 120, "lunch", False)
    assert {r["ingredient_id"]: r["grams"] for r in item["meal_log_item_ingredients"]} == {1: 42, 2: 1.2}


def test_unknown_dish_is_estimated_added_and_then_reused(repo, claude):
    claude.parse_meal.return_value = parsed(("moonu idli", None, "Idli", 3, "piece"))
    claude.estimate.return_value = estimation(
        dishes=[new_dish("Idli", {"piece": 40}, [(1, "Raw Rice", 30), (None, "Urad Dal", 10)])],
        ingredients=[new_ingredient("Urad Dal", protein=24, carbs=60, fat=1.5)],
    )

    log, items = _run(repo, repo.add_log())

    assert log["status"] == "ready"
    assert claude.estimate.call_args.args[0] == ["Idli"]
    idli = next(f for f in repo.foods.values() if f["name"] == "Idli")
    urad = next(i for i in repo.ingredients.values() if i["name"] == "Urad Dal")
    assert idli["recipe"] == [{"ingredient_id": 1, "grams_per_100g": 30}, {"ingredient_id": urad["id"], "grams_per_100g": 10}]
    assert (items[0]["food_id"], items[0]["grams"], items[0]["needs_review"]) == (idli["id"], 120, False)

    # Next time the parse matches it (or names it the same): no second estimate.
    claude.estimate.reset_mock()
    _, again = _run(repo, repo.add_log())
    claude.estimate.assert_not_called()
    assert again[0]["food_id"] == idli["id"] and len(repo.foods) == 1


def test_dish_that_cannot_be_estimated_is_kept_for_review(repo, claude):
    claude.parse_meal.return_value = parsed(("moonu idli", None, "Idli", 3, "piece"))
    claude.estimate.side_effect = RuntimeError("boom")

    log, items = _run(repo, repo.add_log())

    assert log["status"] == "ready"
    assert (items[0]["food_id"], items[0]["grams"], items[0]["needs_review"]) == (None, None, True)
    assert items[0]["meal_log_item_ingredients"] == []


def test_missing_unit_weight_is_added_to_a_known_dish(repo, claude):
    rice = repo.add_food("Cooked Rice", {"karandi": 60}, {1: 35})
    claude.parse_meal.return_value = parsed(("oru plate sadam", rice, "Cooked Rice", 1, "plate"))
    claude.estimate.return_value = estimation(portions=[(rice, "plate", 250), (rice, "cup", 150)])

    _, items = _run(repo, repo.add_log())

    assert repo.foods[rice]["portions"] == {"karandi": 60, "plate": 250}   # only the one asked for
    assert (items[0]["unit"], items[0]["grams"], items[0]["assumed"]) == ("plate", 250, False)


def test_no_amount_means_one_default_serving_marked_assumed(repo, claude):
    rice = repo.add_food("Cooked Rice", {"karandi": 60, "cup": 150}, {1: 35}, default_unit="cup")
    claude.parse_meal.return_value = parsed(("oru karandi sadam", rice, "Cooked Rice", 1, "piece", False))

    _, items = _run(repo, repo.add_log())

    assert (items[0]["quantity"], items[0]["unit"], items[0]["grams"], items[0]["assumed"]) == (1, "cup", 150, True)


def test_her_own_version_of_a_dish_is_used_only_for_her(repo, claude):
    rice = repo.add_food("Cooked Rice", {"karandi": 60}, {1: 35, 2: 1})
    repo.user_recipes[("usr_1", rice)] = [{"ingredient_id": 1, "grams_per_100g": 35},
                                          {"ingredient_id": 2, "grams_per_100g": 0}]
    claude.parse_meal.return_value = parsed(("oru karandi sadam", rice, "Cooked Rice", 1, "karandi"))

    _, hers = _run(repo, repo.add_log("usr_1"))
    _, other = _run(repo, repo.add_log("usr_2"))

    assert hers[0]["used_own_recipe"] and not other[0]["used_own_recipe"]
    assert {r["ingredient_id"]: r["grams"] for r in hers[0]["meal_log_item_ingredients"]} == {1: 21, 2: 0}
    assert {r["ingredient_id"]: r["grams"] for r in other[0]["meal_log_item_ingredients"]} == {1: 21, 2: 0.6}


@pytest.mark.parametrize("transcript, items, error", [
    ("", None, "no_speech"),
    ("inniku workout nalla irundhuchu", parsed(), "no_food"),
    ("sambar saapten", parsed(("rendu vadai", None, "Vadai", 2, "piece")), "no_food"),   # invented item
])
def test_nothing_usable_fails_the_log(repo, claude, transcript, items, error):
    claude.parse_meal.return_value = items

    log, saved = _run(repo, repo.add_log(), transcript)

    assert (log["status"], log["error"], saved) == ("failed", error, [])


def test_a_crash_fails_the_log_and_a_processed_log_is_left_alone(repo, claude):
    claude.parse_meal.side_effect = RuntimeError("refused")
    log, _ = _run(repo, repo.add_log())
    assert (log["status"], log["error"]) == ("failed", "failed")

    done = repo.add_log(status="confirmed")
    pipeline.process_meal_log(repo, done, lambda log: pytest.fail("should not transcribe"))
    assert repo.logs[done]["status"] == "confirmed"


def test_a_log_records_what_it_added_and_what_it_reused(repo, claude):
    rice = repo.add_food("Cooked Rice", {"karandi": 60}, {1: 35})
    claude.parse_meal.return_value = parsed(
        ("moonu idli", None, "Idli", 3, "piece"),
        ("oru karandi sadam", rice, "Cooked Rice", 1, "karandi"),
        ("oru plate sadam", rice, "Cooked Rice", 1, "karandi"),
    )
    claude.estimate.return_value = estimation(
        dishes=[new_dish("Idli", {"piece": 40}, [(1, "Raw Rice", 30), (None, "Urad Dal", 10)])],
        ingredients=[new_ingredient("Urad Dal", protein=24, carbs=60, fat=1.5),
                     new_ingredient("Raw Rice")],          # already there: not new
    )

    log, _ = _run(repo, repo.add_log())

    assert (log["new_food_count"], log["new_ingredient_count"], log["reused_food_count"]) == (1, 1, 2)

    claude.parse_meal.return_value = parsed(("moonu idli", None, "Idli", 3, "piece"))
    again, _ = _run(repo, repo.add_log())
    assert (again["new_food_count"], again["new_ingredient_count"], again["reused_food_count"]) == (0, 0, 1)


def test_a_log_discarded_while_processing_stays_discarded(repo, claude):
    rice = repo.add_food("Cooked Rice", {"karandi": 60}, {1: 35})
    log_id = repo.add_log()

    def parse(*args):
        repo.discard_meal_log(log_id)          # she taps Record again meanwhile
        return parsed(("oru karandi sadam", rice, "Cooked Rice", 1, "karandi"))

    claude.parse_meal.side_effect = parse
    log, _ = _run(repo, log_id)

    assert log["status"] == "discarded"
