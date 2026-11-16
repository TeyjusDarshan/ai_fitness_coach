from datetime import datetime, timezone

import pytest

from diet import service
from diet.test.fakes import FakeRepo


@pytest.fixture
def repo():
    """usr_1 logged 2 karandi (120 g) of rice: 42 g raw rice, 1.2 g oil."""
    repo = FakeRepo()
    rice = repo.add_food("Cooked Rice", {"karandi": 60}, {1: 35, 2: 1})
    log = repo.add_log(status="ready")
    repo.replace_items(log, [{
        "food_id": rice, "food_name": "Cooked Rice", "meal": "lunch", "quote": "rendu karandi sadam",
        "quantity": 2, "unit": "karandi", "grams": 120, "assumed": True, "needs_review": False,
        "used_own_recipe": False,
        "ingredients": [{"ingredient_id": 1, "grams": 42}, {"ingredient_id": 2, "grams": 1.2}],
    }])
    return repo


def _amounts(repo, item_id=1):
    return {r["ingredient_id"]: (r["grams"], r["default_grams"]) for r in repo.get_item(item_id)["meal_log_item_ingredients"]}


def test_item_shape_and_nutrients(repo):
    item = service.shape_item(repo.get_item(1), detail=True, nutrients=True)

    assert (item["name"], item["quantity"], item["unit"], item["grams"]) == ("Cooked Rice", 2, "karandi", 120)
    assert item["protein_g"] == 2.9                      # 42 g rice at 7 g / 100 g
    assert item["nutrients"]["fat_g"] == 1.4             # 0.21 from rice + 1.2 from oil
    assert [i["name"] for i in item["ingredients"]] == ["Raw Rice", "Gingelly Oil"]
    assert item["ingredients"][1]["display_unit"] == "teaspoon"
    assert "nutrients" not in service.shape_item(repo.get_item(1))


def test_changing_the_portion_scales_every_ingredient(repo):
    service.change_quantity(repo, repo.get_item(1), 1)

    item = repo.get_item(1)
    assert (item["quantity"], item["grams"], item["edited"], item["assumed"]) == (1, 60, True, False)
    assert _amounts(repo) == {1: (21, 21), 2: (0.6, 0.6)}
    with pytest.raises(service.EditError):
        service.change_quantity(repo, repo.get_item(1), 50)


def test_changing_an_ingredient_saves_her_version_and_leaves_the_shared_recipe(repo):
    service.change_ingredient(repo, repo.get_item(1), "usr_1", 2, 0)

    assert _amounts(repo) == {1: (42, 42), 2: (0, 1.2)}
    item = repo.get_item(1)
    assert item["edited"] and item["used_own_recipe"]
    assert repo.user_recipes[("usr_1", 1)] == [
        {"ingredient_id": 1, "grams_per_100g": 35}, {"ingredient_id": 2, "grams_per_100g": 0},
    ]
    assert repo.foods[1]["recipe"][1] == {"ingredient_id": 2, "grams_per_100g": 1}
    assert ("usr_2", 1) not in repo.user_recipes


def test_ingredient_edit_is_refused_when_out_of_range_or_not_in_the_dish(repo):
    with pytest.raises(service.EditError):
        service.change_ingredient(repo, repo.get_item(1), "usr_1", 2, 5000)
    with pytest.raises(service.EditError):
        service.change_ingredient(repo, repo.get_item(1), "usr_1", 99, 5)
    assert repo.user_recipes == {}


def test_reset_drops_her_version_and_restores_the_entry(repo):
    service.change_ingredient(repo, repo.get_item(1), "usr_1", 2, 6)
    service.reset_recipe(repo, repo.get_item(1), "usr_1")

    assert _amounts(repo) == {1: (42, 42), 2: (1.2, 1.2)}
    assert repo.user_recipes == {} and not repo.get_item(1)["used_own_recipe"]


def test_day_summary_counts_ready_and_confirmed_logs_only(repo):
    ready = {**repo.logs[1], "meal_log_items": [repo.get_item(1)]}
    processing = {**ready, "id": 2, "status": "processing", "created_at": datetime.now(timezone.utc).isoformat()}

    day = service.day_summary([ready, processing], {"protein_g": 60}, "2026-11-16")

    assert day["totals"] == {"protein_g": 2.9, "fibre_g": 0.4}
    assert day["targets"] == {"protein_g": 60, "fibre_g": 25}
    assert [log["status"] for log in day["logs"]] == ["ready", "processing"]


def test_a_log_stuck_in_processing_shows_as_failed(repo):
    stuck = {**repo.logs[1], "status": "processing", "meal_log_items": []}      # created hours ago

    shaped = service.shape_log(stuck)

    assert (shaped["status"], shaped["error"]) == ("failed", "timeout")
