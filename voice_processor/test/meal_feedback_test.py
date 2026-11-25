"""Tests for meal feedback (voice_processor/meal_feedback.py): each meal of
a WhatsApp check-in judged against its share of her daily targets."""
from unittest.mock import MagicMock

import pytest

from voice_processor import meal_feedback as mf

TARGETS = {"energy_kcal": 1800, "protein_g": 50, "fibre_g": 25, "carbs_g": 225, "fat_g": 60}
LUNCH_ON_TARGET = {"energy_kcal": 630, "protein_g": 17.5, "fibre_g": 8.75, "carbs_g": 78.75, "fat_g": 21}
# 10:00 / 13:30 India time.
MORNING, NOON = "2026-11-23T04:30:00+00:00", "2026-11-23T08:00:00+00:00"


def _item(meal="lunch", needs_review=False, **nutrients):
    return {"dish_name": "Rice", "quantity": 2, "unit": "karandi", "meal": meal,
            "needs_review": needs_review, "nutrients": {**LUNCH_ON_TARGET, **nutrients}}


def _log(*items, id=1, status="ready", skipped=None, created_at=NOON):
    return {"id": id, "status": status, "created_at": created_at, "skipped_meals": skipped or [],
            "logged_for": "2026-11-23", "meal_log_items": list(items)}


def _judge(log, day_logs=None, goal="maintain"):
    return mf.judge_log(log, day_logs or [log], TARGETS, goal, "Asia/Kolkata")


def test_a_meal_on_its_share_is_on_track():
    [verdict] = _judge(_log(_item()))
    assert verdict["status"] == mf.ON_TRACK and verdict["flags"] == {}


def test_within_tolerance_is_not_called_out():
    # kcal 10% band on 630 -> 567..693; carbs 15% band; fat 20% band.
    [verdict] = _judge(_log(_item(energy_kcal=690, carbs_g=90, fat_g=25, protein_g=16)))
    assert verdict["status"] == mf.ON_TRACK


def test_shortfalls_are_flagged_for_every_macro():
    [verdict] = _judge(_log(_item(energy_kcal=300, protein_g=5, fibre_g=2, carbs_g=30, fat_g=5)))
    assert verdict["flags"] == {m: mf.SHORT for m in TARGETS}


def test_over_is_flagged_for_every_macro():
    [verdict] = _judge(_log(_item(energy_kcal=720, protein_g=25, carbs_g=130, fat_g=30, fibre_g=14)))
    assert verdict["flags"] == {m: mf.OVER for m in TARGETS}


def test_calories_over_are_allowed_more_room_when_gaining():
    log = _log(_item(energy_kcal=780))  # 24% over
    assert _judge(log, goal="lose")[0]["flags"] == {"energy_kcal": mf.OVER}
    assert _judge(log, goal="gain")[0]["status"] == mf.ON_TRACK
    assert _judge(_log(_item(energy_kcal=850)), goal="gain")[0]["flags"] == {"energy_kcal": mf.OVER}


def test_a_meal_is_judged_on_everything_logged_for_it_today():
    earlier = _log(_item(energy_kcal=315, protein_g=9, fibre_g=4.5, carbs_g=40, fat_g=10.5), id=1)
    now = _log(_item(energy_kcal=315, protein_g=9, fibre_g=4.5, carbs_g=40, fat_g=10.5), id=2)
    assert _judge(earlier)[0]["flags"]           # half a lunch is short on its own
    assert _judge(now, [earlier, now])[0]["status"] == mf.ON_TRACK


def test_discarded_and_failed_logs_do_not_count():
    gone = _log(_item(), id=1, status="failed")
    now = _log(_item(energy_kcal=315), id=2)
    assert _judge(now, [gone, now])[0]["flags"]["energy_kcal"] == mf.SHORT


def test_a_dish_with_no_meal_counts_by_when_it_was_logged():
    log = _log(_item(meal=None), created_at=MORNING)
    [verdict] = _judge(log)
    assert verdict["meal"] == "breakfast"


def test_a_skipped_meal_gets_a_nudge_not_macros():
    [verdict] = _judge(_log(skipped=["breakfast"]))
    assert verdict == {"meal": "breakfast", "status": mf.SKIPPED, "flags": {}, "dishes": []}


def test_a_meal_with_an_unworked_out_dish_is_not_judged():
    [verdict] = _judge(_log(_item(energy_kcal=10), _item(needs_review=True)))
    assert verdict["status"] == mf.UNKNOWN and verdict["flags"] == {}


def test_coach_targets_are_used_with_defaults_for_the_rest():
    verdicts = mf.judge_log(_log(_item(energy_kcal=630)), [_log(_item(energy_kcal=630))],
                            {"energy_kcal": 3000}, "maintain", "Asia/Kolkata")
    assert verdicts[0]["flags"] == {"energy_kcal": mf.SHORT}


def test_reply_shows_numbers_against_the_meals_share_with_emoji():
    log = _log(_item(protein_g=5, carbs_g=130))
    text = mf.build_feedback(log, [log], TARGETS, "maintain", name="Priya")["text"]
    assert text.startswith("Priya, lunch")
    assert "Kcal 630 / 630 ✅" in text
    assert "Protein 5 / 18 g 🔻" in text
    assert "Carbs 130 / 79 g 🔺" in text
    assert "romba" not in text and "kammi" not in text and "adhigam" not in text


def test_a_block_per_meal_and_unlogged_meals_listed():
    log = _log(_item(), _item(meal="breakfast", energy_kcal=450, protein_g=12.5, fibre_g=6.25,
                              carbs_g=56.25, fat_g=15))
    text = mf.build_feedback(log, [log], TARGETS, "maintain", name="Priya")["text"]
    assert "Breakfast\nKcal" in text and "Lunch\nKcal" in text
    assert text.endswith("Innum log pannala: Snacks & Dinner")
    assert mf.ALL_GOOD in text


def test_all_good_line_only_when_nothing_is_off():
    log = _log(_item(protein_g=5))
    assert mf.ALL_GOOD not in mf.build_feedback(log, [log], TARGETS, None)["text"]


def test_no_name_falls_back_to_noted():
    log = _log(_item())
    assert mf.build_feedback(log, [log], TARGETS, None)["text"].startswith(mf.TOOK_NOTE)


def test_skipped_meal_is_not_listed_as_unlogged():
    log = _log(skipped=["breakfast"])
    text = mf.build_feedback(log, [log], TARGETS, None, name="Priya")["text"]
    assert "skip pannirukeenga" in text and "Innum log pannala: Lunch, Snacks & Dinner" in text


@pytest.fixture
def diet_repo():
    repo = MagicMock()
    repo.get_profile_basics.return_value = {"name": "Priya", "diet_setup": {"goal": "lose"}}
    repo.get_targets.return_value = None
    return repo


def test_send_texts_the_reply_and_stores_only_the_send_time(diet_repo):
    log = _log(_item(fat_g=40), id=9)
    diet_repo.get_meal_log_detail.return_value = log
    diet_repo.list_meal_logs.return_value = [log]
    whatsapp = MagicMock()

    result = mf.send_feedback(diet_repo, whatsapp, 9, "u1", "9199", "Asia/Kolkata")

    whatsapp.send_text.assert_called_once_with("9199", result["text"])
    whatsapp.send_audio.assert_not_called()
    [call] = diet_repo.update_meal_log.call_args_list
    assert list(call.args[1]) == ["feedback_sent_at"]
