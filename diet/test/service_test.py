from datetime import datetime, timezone

import pytest

from diet import service
from diet.test.fakes import FakeRepo


@pytest.fixture
def repo():
    """usr_1 logged 2 karandi (120 g) of rice: 42 g raw rice, 1.2 g oil."""
    repo = FakeRepo()
    log = repo.add_log(status="ready")
    repo.add_item(log, "Cooked Rice", {1: 42, 2: 1.2}, meal="lunch", quote="rendu karandi sadam",
                  quantity=2, unit="karandi", portion_grams=120, assumed=True)
    return repo


def _amounts(repo, item_id=1):
    return {r["reference_id"]: (r["grams"], r["default_grams"]) for r in repo.get_item(item_id)["meal_log_item_ingredients"]}


def test_item_shape_and_nutrients(repo):
    item = service.shape_item(repo.get_item(1), detail=True, nutrients=True)

    assert (item["name"], item["quantity"], item["unit"], item["grams"]) == ("Cooked Rice", 2, "karandi", 120)
    assert item["protein_g"] == 2.9                      # 42 g rice at 7 g / 100 g
    assert item["nutrients"]["fat_g"] == 1.4             # 0.21 from rice + 1.2 from oil
    assert item["nutrients"]["vitamin_b6_mg"] == 0       # every nutrient key, unknown as 0
    assert [i["name"] for i in item["ingredients"]] == ["Raw white rice", "Sesame (gingelly) oil"]
    assert item["ingredients"][1]["display_unit"] == "teaspoon"
    assert "nutrients" not in service.shape_item(repo.get_item(1))


def test_changing_the_portion_scales_every_ingredient_and_the_nutrients(repo):
    service.change_quantity(repo, repo.get_item(1), 1)

    item = repo.get_item(1)
    assert (item["quantity"], item["portion_grams"], item["edited"], item["assumed"]) == (1, 60, True, False)
    assert _amounts(repo) == {1: (21, 21), 2: (0.6, 0.6)}
    assert service.shape_item(item)["protein_g"] == 1.5
    with pytest.raises(service.EditError):
        service.change_quantity(repo, repo.get_item(1), 50)


def test_changing_an_ingredient_changes_only_this_entry(repo):
    service.change_ingredient(repo, repo.get_item(1), 2, 0)

    assert _amounts(repo) == {1: (42, 42), 2: (0, 1.2)}
    item = repo.get_item(1)
    assert item["edited"] and round(item["nutrients"]["fat_g"], 2) == 0.21


def test_ingredient_edit_is_refused_when_out_of_range_or_not_in_the_dish(repo):
    with pytest.raises(service.EditError):
        service.change_ingredient(repo, repo.get_item(1), 2, 5000)
    with pytest.raises(service.EditError):
        service.change_ingredient(repo, repo.get_item(1), 99, 5)


def test_reset_goes_back_to_the_estimate(repo):
    service.change_ingredient(repo, repo.get_item(1), 2, 6)
    service.reset_item(repo, repo.get_item(1))

    assert _amounts(repo) == {1: (42, 42), 2: (1.2, 1.2)}
    assert round(repo.get_item(1)["nutrients"]["fat_g"], 2) == 1.41


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
