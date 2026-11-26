"""Tests for weight tracking on WhatsApp: the Sunday close and the nudges
(voice_processor/weight_jobs.py), a weight check-in (weight_checkin.py) and
the router's new label. Repositories, WhatsApp and Claude are mocked."""
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from diet.weight import rules
from voice_processor import router, weight_checkin, weight_jobs as wj
from voice_processor.router_agent import WEIGHT_CHECKIN

IST = ZoneInfo("Asia/Kolkata")
WEEK = date(2026, 11, 16)                      # Mon; its Sunday is 22 Nov
SUNDAY_EVENING = datetime(2026, 11, 22, 19, 30, tzinfo=IST)
SETUP = {"height_cm": 160, "weight_kg": 74.0, "age": 52, "goal": "lose", "target_weight_kg": 68.0,
         "weekly_change_kg": 0.4, "completed_at": "2026-10-05T05:00:00+00:00"}


def client(**overrides):
    row = {"user_id": "u1", "name": "Priya", "gender": "female", "timezone": "Asia/Kolkata",
           "whatsapp_number": "919876543210", "diet_setup": SETUP, "nutrition_targets": {"energy_kcal": 1500},
           "weight_goal": None, "weight_goal_kg": None}
    row.update(overrides)
    return row


def readings(start, weights):
    return [{"measured_on": (start + timedelta(days=i)).isoformat(), "weight_kg": w} for i, w in enumerate(weights)]


def meal_logs(start, days, kcal=1500):
    """Breakfast, lunch and dinner logged every day."""
    logs = []
    for i in range(days):
        logs.append({"status": "ready", "logged_for": (start + timedelta(days=i)).isoformat(),
                     "created_at": "2026-11-10T03:00:00+00:00", "skipped_meals": [],
                     "meal_log_items": [{"meal": m, "nutrients": {"energy_kcal": kcal / 3}}
                                        for m in ("breakfast", "lunch", "dinner")]})
    return logs


@pytest.fixture
def repo():
    repo = MagicMock()
    repo.get_week.return_value = None
    repo.list_readings.return_value = (readings(WEEK - timedelta(weeks=1), [72.6, 72.5, 72.4, 72.5])
                                       + readings(WEEK, [72.5, 72.4, 72.3, 72.4, 72.4]))  # 72.5 -> 72.4: stalled
    repo.list_changes.return_value = []
    repo.list_weeks.return_value = []
    repo.period_days.return_value = []
    repo.reply_window_open.return_value = True
    repo.create_week.return_value = {"id": 40}
    return repo


@pytest.fixture
def diet_repo():
    diet_repo = MagicMock()
    diet_repo.list_meal_logs.side_effect = lambda user_id, start, end: meal_logs(start, (end - start).days + 1)
    return diet_repo


@pytest.fixture
def sender():
    return MagicMock()


def close(repo, diet_repo, sender, mode, now=SUNDAY_EVENING, **overrides):
    return wj.close_week(repo, diet_repo, client(**overrides), now, lambda: sender, mode=mode)


# --- which week, and the food gate ---------------------------------------------

def test_the_week_closes_at_sunday_19_00_her_time():
    assert wj.closing_week(datetime(2026, 11, 22, 18, 59, tzinfo=IST)) == WEEK - timedelta(weeks=1)
    assert wj.closing_week(datetime(2026, 11, 22, 19, 0, tzinfo=IST)) == WEEK
    assert wj.closing_week(datetime(2026, 11, 25, 9, 0, tzinfo=IST)) == WEEK


def test_food_gate_counts_main_meals_and_averages_logged_days():
    start, end = date(2026, 11, 9), date(2026, 11, 22)
    logs = meal_logs(start, 10, kcal=1500)
    logs[0]["meal_log_items"] = logs[0]["meal_log_items"][:1]
    logs[1]["skipped_meals"] = ["breakfast"]
    logs[2]["status"] = "failed"
    gate = wj.food_gate(logs, start, end, "Asia/Kolkata")
    assert gate["meals_total"] == 42
    assert gate["meals_logged"] == 1 + 3 + 0 + 7 * 3
    assert gate["avg_kcal"] == round((500 + 1500 * 8) / 9)


# --- closing a week ------------------------------------------------------------

def test_shadow_mode_stores_the_decision_and_sends_nothing(repo, diet_repo, sender):
    assert close(repo, diet_repo, sender, wj.SHADOW) == rules.WAIT
    row = repo.create_week.call_args.args[0]
    assert (row["week_start"], row["outcome"], row["classification"], row["streak"]) == ("2026-11-16", "wait", "stalled", 1)
    assert row["streak_stalled"] is True
    assert (row["avg_kg"], row["previous_avg_kg"], row["readings"], row["status"]) == (72.4, 72.5, 5, "shadow")
    assert "Average: 72.4 kg (pona vaaram 72.5)" in row["message_text"]
    sender.send.assert_not_called()
    repo.create_change.assert_not_called()


def test_live_mode_sends_the_summary_when_the_window_is_open(repo, diet_repo, sender):
    close(repo, diet_repo, sender, wj.LIVE)
    assert repo.create_week.call_args.args[0]["status"] == "pending"
    sender.send.assert_called_once()
    assert repo.update_week.call_args.args[1]["status"] == "sent"


def test_live_mode_skips_when_the_window_is_closed_or_the_close_is_late(repo, diet_repo, sender):
    repo.reply_window_open.return_value = False
    close(repo, diet_repo, sender, wj.LIVE)
    assert repo.create_week.call_args.args[0]["status"] == "skipped_window_closed"
    repo.reply_window_open.return_value = True
    close(repo, diet_repo, sender, wj.LIVE, now=SUNDAY_EVENING + timedelta(days=2))
    assert repo.create_week.call_args.args[0]["status"] == "skipped_late"
    sender.send.assert_not_called()


def test_a_second_bad_week_suggests_a_cut_to_the_coach_in_live_mode(repo, diet_repo, sender):
    repo.list_weeks.return_value = [{"week_start": "2026-11-09", "streak": 1, "streak_stalled": False,
                                     "streak_direction": None}]
    assert close(repo, diet_repo, sender, wj.LIVE) == rules.LOWER
    repo.supersede_pending.assert_called_once_with("u1")
    change = repo.create_change.call_args.args[0]
    assert (change["source"], change["status"], change["week_id"]) == ("weekly_rule", "pending", 40)
    assert change["from_targets"]["energy_kcal"] == 1500 and change["to_targets"]["energy_kcal"] == 1350
    assert repo.create_week.call_args.args[0]["proposed_kcal"] == 1350


def test_a_cut_at_her_floor_becomes_at_floor_with_no_suggestion(repo, diet_repo, sender):
    repo.list_weeks.return_value = [{"week_start": "2026-11-09", "streak": 1, "streak_stalled": False,
                                     "streak_direction": None}]
    diet_repo.list_meal_logs.side_effect = lambda user_id, start, end: meal_logs(start, (end - start).days + 1, 1300)
    assert close(repo, diet_repo, sender, wj.LIVE, nutrition_targets={"energy_kcal": 1300}) == rules.AT_FLOOR
    repo.create_change.assert_not_called()


def test_reaching_the_target_suggests_a_switch_to_maintain(repo, diet_repo, sender):
    repo.list_readings.return_value = (readings(WEEK - timedelta(weeks=1), [68.9] * 4)
                                       + readings(WEEK, [68.5, 68.4, 68.4, 68.3]))
    assert close(repo, diet_repo, sender, wj.LIVE) == rules.TARGET_REACHED
    change = repo.create_change.call_args.args[0]
    assert (change["source"], change["new_goal"], change["new_goal_kg"]) == ("goal_switch", "maintain", 68.4)


def test_a_week_is_closed_once_and_not_before_her_setup(repo, diet_repo, sender):
    repo.get_week.return_value = {"id": 1}
    assert close(repo, diet_repo, sender, wj.LIVE) == "already_closed"
    repo.get_week.return_value = None
    late_setup = {**SETUP, "completed_at": "2026-11-24T05:00:00+00:00"}
    assert close(repo, diet_repo, sender, wj.LIVE, diet_setup=late_setup) == "before_setup"
    repo.create_week.assert_not_called()


def test_the_week_after_an_accepted_change_is_a_baseline(repo, diet_repo, sender):
    repo.list_changes.return_value = [{"status": "accepted", "decided_at": "2026-11-17T06:00:00+00:00",
                                       "created_at": "2026-11-17T06:00:00+00:00"}]
    assert close(repo, diet_repo, sender, wj.SHADOW) == rules.BASELINE
    assert "Pudhu food plan" in repo.create_week.call_args.args[0]["message_text"]


# --- nudges --------------------------------------------------------------------

def test_the_how_to_goes_first_and_only_while_the_window_is_open(repo, sender):
    repo.intro_sent.return_value = False
    repo.reply_window_open.return_value = False
    assert wj.nudge(repo, client(), SUNDAY_EVENING, lambda: sender) == "intro_waiting"
    repo.reply_window_open.return_value = True
    repo.create_nudge.return_value = {"id": 3}
    assert wj.nudge(repo, client(), SUNDAY_EVENING, lambda: sender) == "sent"
    assert repo.create_nudge.call_args.args[0]["kind"] == "intro"
    assert "dhinamum kaalaila" in sender.send.call_args.args[1]


def test_the_morning_nudge_at_10_unless_she_already_weighed_in(repo, sender):
    repo.intro_sent.return_value = True
    repo.get_nudge.return_value = None
    ten = datetime(2026, 11, 24, 10, 5, tzinfo=IST)
    assert wj.nudge(repo, client(), ten.replace(hour=9), lambda: sender) == "not_due"
    repo.has_reading.return_value = True
    assert wj.nudge(repo, client(), ten, lambda: sender) == "skipped_logged"
    repo.has_reading.return_value = False
    repo.reply_window_open.return_value = False
    assert wj.nudge(repo, client(), ten, lambda: sender) == "skipped_window_closed"
    repo.reply_window_open.return_value = True
    repo.create_nudge.return_value = {"id": 4}
    assert wj.nudge(repo, client(), ten, lambda: sender) == "sent"
    assert sender.send.call_args.args[1].startswith("Priya, inniki weight")


# --- a check-in ----------------------------------------------------------------

def test_a_check_in_saves_and_says_noted(repo):
    whatsapp = MagicMock()
    repo.list_readings.return_value = readings(date(2026, 11, 20), [72.0, 72.2])
    repo.upsert_reading.return_value = {"id": 77}
    assert weight_checkin.handle(repo, whatsapp, "u1", "91x", 72.1, "audio", "72 point 1", 5, "Asia/Kolkata") == 77
    assert repo.upsert_reading.call_args.args[0]["source"] == "whatsapp_voice"
    whatsapp.send_text.assert_called_once_with("91x", "Noted ✅ 72.1 kg")


def test_a_check_in_far_from_her_week_or_without_a_number_isnt_saved(repo):
    whatsapp = MagicMock()
    repo.list_readings.return_value = readings(date(2026, 11, 20), [72.0, 72.2])
    assert weight_checkin.handle(repo, whatsapp, "u1", "91x", 75.0, "text", "75", 5, None) is None
    assert "check panni" in whatsapp.send_text.call_args.args[1]
    assert weight_checkin.handle(repo, whatsapp, "u1", "91x", None, "text", "weight?", 5, None) is None
    assert "Number mattum" in whatsapp.send_text.call_args.args[1]
    repo.upsert_reading.assert_not_called()


# --- the router ----------------------------------------------------------------

def test_weight_label_only_once_diet_tracking_is_set_up():
    assert WEIGHT_CHECKIN not in router.allowed_labels(False, True)
    assert router.allowed_labels(False, True, True) == ["diet_checkin", "weight_checkin", "other"]


def test_router_hands_a_weight_to_the_check_in(monkeypatch):
    workout_repo, weight_repo = MagicMock(), MagicMock()
    workout_repo.get_profile_for_routing.return_value = {
        "user_id": "u1", "diet_enabled": True, "diet_setup": SETUP, "timezone": "Asia/Kolkata"}
    workout_repo.get_or_create_inbound.return_value = {"id": 5}
    workout_repo.find_open_clarification.return_value = None
    workout_repo.recent_meal_reminder.return_value = None
    weight_repo.recent_nudge.return_value = {"sent_at": "2026-11-26T04:30:00+00:00"}
    seen = {}

    def classify(payload, user_id=None):
        seen.update(payload)
        return SimpleNamespace(label=WEIGHT_CHECKIN, day="today", weight_kg=72.4, reason="A number.")

    monkeypatch.setattr(router.router_agent, "classify_message", classify)
    handled = MagicMock(return_value=77)
    monkeypatch.setattr(router.weight_checkin, "handle", handled)
    router.handle_inbound(workout_repo, MagicMock(), {
        "phone_number": "91x", "whatsapp_message_id": "wamid.9", "type": "text", "text": "72.4"}, weight_repo)
    assert "weight_checkin" in seen["allowed_labels"] and "weigh_in_nudge" in seen
    assert handled.call_args.args[2:6] == ("u1", "91x", 72.4, "text")
    assert workout_repo.update_inbound.call_args.args[1]["weight_log_id"] == 77
