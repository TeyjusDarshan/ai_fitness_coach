"""Tests for weight tracking's service, targets and messages
(diet/weight/service.py, targets.py, messages.py). The repository is mocked."""
from datetime import date, timedelta
from unittest.mock import MagicMock

from diet.weight import messages, rules, service, targets

TODAY = date(2026, 11, 26)  # a Thursday
MONDAY = date(2026, 11, 23)
SETUP = {"height_cm": 160, "weight_kg": 74.0, "age": 52, "goal": "lose", "target_weight_kg": 68.0,
         "weekly_change_kg": 0.4, "completed_at": "2026-10-05T05:00:00+00:00"}


def profile(**overrides):
    row = {"user_id": "u1", "name": "Priya", "gender": "female", "timezone": "Asia/Kolkata",
           "diet_setup": SETUP, "nutrition_targets": {"energy_kcal": 1500}, "weight_goal": None,
           "weight_goal_kg": None, "whatsapp_number": "919876543210"}
    row.update(overrides)
    return row


def readings(start, weights):
    return [{"measured_on": (start + timedelta(days=i)).isoformat(), "weight_kg": w}
            for i, w in enumerate(weights) if w is not None]


# --- saving a reading ----------------------------------------------------------

def test_a_reading_is_saved_for_her_day_and_replaces_an_earlier_one():
    repo = MagicMock()
    repo.list_readings.return_value = readings(TODAY - timedelta(days=7), [72.0, 72.2, 71.8])
    repo.upsert_reading.return_value = {"id": 9}
    status, weight, row = service.record_reading(repo, "u1", 72.44, "whatsapp_text", TODAY, 5, "72.44")
    assert (status, weight, row) == (service.SAVED, 72.4, {"id": 9})
    saved = repo.upsert_reading.call_args.args[0]
    assert saved["measured_on"] == TODAY.isoformat() and saved["inbound_message_id"] == 5
    # The look-back stops yesterday, so today's earlier reading doesn't judge its correction.
    assert repo.list_readings.call_args.args[1:] == (TODAY - timedelta(days=7), TODAY - timedelta(days=1))


def test_an_outlier_or_a_bad_number_is_not_saved():
    repo = MagicMock()
    repo.list_readings.return_value = readings(TODAY - timedelta(days=3), [72.0, 72.0])
    assert service.record_reading(repo, "u1", 74.5, "whatsapp_text", TODAY)[:2] == (service.OUTLIER, 74.5)
    assert service.record_reading(repo, "u1", None, "whatsapp_text", TODAY)[0] == service.INVALID
    assert service.record_reading(repo, "u1", 250, "whatsapp_text", TODAY)[0] == service.INVALID
    repo.upsert_reading.assert_not_called()


# --- her plan ------------------------------------------------------------------

def test_plan_follows_setup_until_a_goal_switch():
    plan = service.plan_of(profile())
    assert (plan["goal"], plan["goal_kg"], plan["start_kg"], plan["expected_kg"]) == ("lose", 68.0, 74.0, 0.4)
    assert plan["band"] is None
    switched = service.plan_of(profile(weight_goal="maintain", weight_goal_kg=68.2))
    assert switched["goal"] == "maintain" and switched["band"]["center_kg"] == 68.2
    assert switched["expected_kg"] is None
    keeping = service.plan_of(profile(diet_setup={**SETUP, "goal": "maintain", "target_weight_kg": None}))
    assert keeping["goal_kg"] == 74.0 and keeping["band"]["lower_kg"] == 72.2


def test_settling_weeks_after_setup_and_after_a_change():
    change_day = date(2026, 11, 10)  # a Tuesday
    week_of_change = rules.week_start(change_day)
    assert service.settling(week_of_change, None, [change_day]) == rules.BASELINE
    assert service.settling(week_of_change + timedelta(weeks=1), None, [change_day]) == rules.COOL_DOWN
    assert service.settling(week_of_change + timedelta(weeks=2), None, [change_day]) is None
    assert service.settling(week_of_change - timedelta(weeks=1), None, [change_day]) is None
    assert service.settling(rules.week_start(date(2026, 10, 5)), date(2026, 10, 5), []) == rules.BASELINE


# --- her view ------------------------------------------------------------------

def test_view_before_her_first_full_week_asks_for_more_days():
    rows = readings(MONDAY, [72.0, 71.8])
    view = service.view(profile(), rows, None, [], MONDAY + timedelta(days=1), 8)
    assert view["chart"] == {"unlocked": False, "readings_needed": 2, "unlocks_on": "2026-11-29", "weeks": []}
    assert view["today"] == {"date": "2026-11-24", "weight_kg": 71.8}
    assert view["this_week"]["average_kg"] == 71.9 and view["last_week"]["average_kg"] is None
    assert view["change_vs_last_week_kg"] is None


def test_view_with_weeks_of_readings():
    last_monday = MONDAY - timedelta(weeks=1)
    rows = readings(last_monday - timedelta(weeks=1), [73.0] * 5) + readings(last_monday, [72.6, 72.4, 72.5, 72.5]) \
        + readings(MONDAY, [72.2, None, 72.0, 71.9])
    changes = [{"status": "accepted", "decided_at": "2026-11-17T06:00:00+00:00", "created_at": "x",
                "from_targets": {"energy_kcal": 1600}, "to_targets": {"energy_kcal": 1500}},
               {"status": "pending", "created_at": "2026-11-24T06:00:00+00:00", "to_targets": {"energy_kcal": 1400}}]
    latest = {"week_start": last_monday.isoformat(), "outcome": "on_track", "classification": "on_track"}
    view = service.view(profile(), rows, latest, changes, TODAY, 8)
    assert view["today"]["weight_kg"] == 71.9
    assert view["this_week"] == {"week_start": "2026-11-23", "average_kg": 72.03, "readings": 3}
    assert view["last_week"]["average_kg"] == 72.5
    assert view["change_vs_last_week_kg"] == -0.47 and view["toward_goal"] is True
    assert view["chart"]["unlocked"] is True
    assert [w["average_kg"] for w in view["chart"]["weeks"]] == [73.0, 72.5]
    assert view["calorie_changes"] == [{"date": "2026-11-17", "from_kcal": 1600, "to_kcal": 1500}]
    assert view["status"]["outcome"] == "on_track"
    assert view["target_weight_kg"] == 68.0 and view["band"] is None


def test_view_range_keeps_only_the_last_n_weeks():
    rows = []
    for back in range(1, 7):
        rows += readings(MONDAY - timedelta(weeks=back), [70.0 + back] * 4)
    view = service.view(profile(), rows, None, [], TODAY, 4)
    assert [w["week_start"] for w in view["chart"]["weeks"]] == [
        (MONDAY - timedelta(weeks=n)).isoformat() for n in (4, 3, 2, 1)]


# --- targets -------------------------------------------------------------------

PERSON = targets.body(SETUP, "female")


def test_a_cut_stops_at_her_floor_and_none_when_already_there():
    floor = targets.floor_kcal(72.0, PERSON)
    assert floor == 1299.0  # her BMR at 72 kg, above the 1200 minimum
    assert targets.changed_targets(1500, -150, "lose", 72.0, PERSON)["energy_kcal"] == 1350
    assert targets.changed_targets(1400, -150, "lose", 72.0, PERSON)["energy_kcal"] == 1300
    assert targets.changed_targets(1300, -100, "lose", 72.0, PERSON) is None
    assert targets.floor_kcal(40.0, PERSON) == 1200  # a small client: the 1200 minimum wins


def test_a_gain_raise_is_capped_at_maintenance_plus_500():
    top = targets.maintenance_kcal(55.0, PERSON) + targets.GAIN_CEILING_OVER_MAINTENANCE
    result = targets.changed_targets(top - 50, 150, "gain", 55.0, PERSON)
    assert result["energy_kcal"] == round(top / 10) * 10


def test_maintenance_targets_have_full_macros():
    result = targets.maintenance_targets(68.0, PERSON)
    assert set(result) == {"energy_kcal", "protein_g", "carbs_g", "fat_g", "fibre_g"}
    assert result["protein_g"] == round(1.2 * min(68.0, 24.9 * 1.6 ** 2))


# --- messages ------------------------------------------------------------------

def test_weekly_summaries_are_short_and_name_two_weights_at_most():
    ctx = {"name": "Priya", "readings": 6, "avg_kg": 72.2, "previous_avg_kg": 72.6, "change_kg": -0.4,
           "meals_logged": 19, "meals_total": 21, "goal_kg": 68.0}
    for outcome in (rules.ON_TRACK, rules.WAIT, rules.PERIOD_WEEK, rules.LOGS_LOW, rules.LOWER,
                    rules.TOO_FAST, rules.TARGET_REACHED, rules.COOL_DOWN, rules.CHANGE_PENDING, rules.AT_FLOOR):
        text = messages.weekly_summary(outcome, "lose", ctx)
        assert len(text.splitlines()) <= 5, outcome
        assert "Average: 72.2 kg (pona vaaram 72.6) ↓ 0.4 kg" in text
    first = messages.weekly_summary(rules.BASELINE, "lose", {**ctx, "previous_avg_kg": None})
    assert "starting average" in first and "pona vaaram" not in first
    missing = messages.weekly_summary(rules.NOT_ENOUGH_DATA, "lose", {**ctx, "readings": 3})
    assert "3 naal" in missing and "Average" not in missing


def test_reply_texts():
    assert messages.noted(72.44) == "Noted ✅ 72.4 kg"
    assert "72.0 kg" in messages.outlier(72)
    assert "1600 → 1450" in messages.change_approved("Priya", 1600, 1450, rules.LOWER, "lose")
    assert "maintain" in messages.change_approved("Priya", 1450, 1700, rules.TARGET_REACHED, "lose")
