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


def test_more_protein_or_fibre_is_never_called_out():
    [verdict] = _judge(_log(_item(protein_g=60, fibre_g=30)))
    assert verdict["status"] == mf.ON_TRACK


def test_over_and_well_over():
    [verdict] = _judge(_log(_item(energy_kcal=720, carbs_g=130, fat_g=30)))
    assert verdict["flags"] == {"energy_kcal": mf.OVER, "carbs_g": mf.BIG, "fat_g": mf.OVER}


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


def test_on_track_reply_is_a_free_text_with_no_tip():
    tip = MagicMock()
    feedback = mf.build_feedback(_log(_item()), [_log(_item())], TARGETS, "lose", get_tip=tip)
    assert feedback["voice"] is False and feedback["tip"] is None
    assert "Lunch correct-a irukku, you are on track" in feedback["text"]
    tip.assert_not_called()


def test_off_reply_names_macros_without_numbers_and_adds_the_tip():
    log = _log(_item(protein_g=5, carbs_g=130), _item(meal="breakfast", energy_kcal=450, protein_g=12.5,
                                                    fibre_g=6.25, carbs_g=56.25, fat_g=15))
    tip = MagicMock(return_value="Next time konjam sundal add pannunga.")
    feedback = mf.build_feedback(log, [log], TARGETS, "maintain", get_tip=tip)

    assert feedback["voice"] is True
    text = feedback["text"]
    assert "Lunch-la protein konjam kammi, carbs romba adhigam." in text
    assert "Breakfast correct-a irukku." in text
    assert "sundal" in text and mf.APP_POINTER in text
    assert not any(ch.isdigit() for ch in text)
    off_meals, goal = tip.call_args.args
    assert [v["meal"] for v in off_meals] == ["lunch"] and goal == "maintain"


def test_a_failed_tip_still_sends_the_template():
    log = _log(_item(protein_g=5))
    feedback = mf.build_feedback(log, [log], TARGETS, None, get_tip=MagicMock(side_effect=RuntimeError("boom")))
    assert feedback["tip"] is None and "protein konjam kammi" in feedback["text"]


def test_spoken_text_drops_emoji():
    assert mf.spoken("Noted 👍 Keep it up 💪") == "Noted Keep it up"


@pytest.fixture
def diet_repo():
    repo = MagicMock()
    repo.get_profile_basics.return_value = {"diet_setup": {"goal": "lose"}}
    repo.get_targets.return_value = None
    return repo


def test_send_on_track_stores_then_texts(diet_repo, monkeypatch):
    log = _log(_item(), id=9)
    diet_repo.get_meal_log_detail.return_value = log
    diet_repo.list_meal_logs.return_value = [log]
    whatsapp = MagicMock()
    voice = MagicMock()
    monkeypatch.setattr(mf, "_voice_note", voice)

    result = mf.send_feedback(diet_repo, whatsapp, 9, "u1", "9199", "Asia/Kolkata")

    assert result["sent_as"] == "text"
    whatsapp.send_text.assert_called_once_with("9199", result["text"])
    voice.assert_not_called()
    stored = diet_repo.update_meal_log.call_args_list[0].args[1]
    assert stored["feedback"] == result["text"]
    assert stored["feedback_flags"]["verdicts"] == [{"meal": "lunch", "status": "on_track", "flags": {}}]
    assert "feedback_sent_at" in diet_repo.update_meal_log.call_args_list[1].args[1]


def test_send_off_is_a_voice_note_and_falls_back_to_text(diet_repo, monkeypatch):
    log = _log(_item(fat_g=40), id=9)
    diet_repo.get_meal_log_detail.return_value = log
    diet_repo.list_meal_logs.return_value = [log]
    monkeypatch.setattr(mf.meal_feedback_agent, "write_tip", MagicMock(return_value="Ennai konjam kammi pannunga."))
    monkeypatch.setattr(mf, "_voice_note", MagicMock(return_value="https://x/meal_9.ogg"))
    whatsapp = MagicMock()

    result = mf.send_feedback(diet_repo, whatsapp, 9, "u1", "9199")
    assert result["sent_as"] == "audio"
    whatsapp.send_audio.assert_called_once_with("9199", "https://x/meal_9.ogg")
    whatsapp.send_text.assert_not_called()
    assert diet_repo.update_meal_log.call_args_list[1].args[1]["feedback_audio_url"] == "https://x/meal_9.ogg"

    whatsapp = MagicMock()
    monkeypatch.setattr(mf, "_voice_note", MagicMock(side_effect=RuntimeError("sarvam down")))
    result = mf.send_feedback(diet_repo, whatsapp, 9, "u1", "9199")
    assert result["sent_as"] == "text"
    whatsapp.send_text.assert_called_once()
