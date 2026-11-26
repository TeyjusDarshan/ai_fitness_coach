"""Tests for the weekly weight rules (diet/weight/rules.py): one test per box
of the lose / gain / maintain flowcharts, in the same order."""
from datetime import date

import pytest

from diet.weight import rules as r


def week(goal="lose", avg=72.0, previous=72.5, **overrides):
    values = dict(goal=goal, readings=6, avg_kg=avg, previous_avg_kg=previous, expected_kg=0.45,
                  goal_kg={"lose": 68.0, "gain": 60.0, "maintain": None}[goal], period_week=False,
                  log_coverage=0.8, avg_logged_kcal=1600, target_kcal=1600)
    values.update(overrides)
    return r.WeekInput(**values)


# --- a reading ---------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    (72.44, 72.4), (72, 72.0), (30, 30.0), (200, 200.0),
    (29.9, None), (200.1, None), (None, None), ("72", None), (True, None), (float("nan"), None),
])
def test_validate_weight(value, expected):
    assert r.validate_weight(value) == expected


def test_outlier_is_more_than_2_kg_from_the_recent_average():
    recent = [72.0, 72.4, 71.6]  # average 72.0
    assert not r.is_outlier(74.0, recent)
    assert r.is_outlier(74.1, recent)
    assert r.is_outlier(69.9, recent)
    assert not r.is_outlier(90.0, [])  # no history: nothing is an outlier


def test_week_average_needs_four_readings_and_weeks_start_on_monday():
    assert r.week_average([70, 71, 72]) is None
    assert r.week_average([70, 71, 72, 73]) == 71.5
    assert r.week_start(date(2026, 11, 26)) == date(2026, 11, 23)  # Thursday -> Monday
    assert r.week_start(date(2026, 11, 29)) == date(2026, 11, 23)  # Sunday stays in that week


def test_maintain_band_is_two_and_a_half_percent_and_toward_goal():
    band = r.maintain_band(70.0)
    assert band == {"center_kg": 70.0, "lower_kg": 68.2, "upper_kg": 71.8}
    assert r.toward_goal("maintain", 0.5, 71.0, band) is True
    assert r.toward_goal("maintain", 0.5, 72.0, band) is False
    assert r.toward_goal("lose", -0.2, 71.0) is True
    assert r.toward_goal("lose", 0.2, 71.0) is False
    assert r.toward_goal("gain", 0.2, 61.0) is True
    assert r.toward_goal("gain", None, 61.0) is None


# --- shared first boxes ------------------------------------------------------

@pytest.mark.parametrize("goal", r.GOALS)
def test_fewer_than_four_readings_holds_and_keeps_the_streak(goal):
    streak = r.Streak(1, True, "up")
    d = r.decide(week(goal, avg=None, readings=3, previous_streak=streak))
    assert d.outcome == r.NOT_ENOUGH_DATA and d.streak == streak and d.kcal_delta == 0


@pytest.mark.parametrize("goal", r.GOALS)
def test_no_average_last_week_is_a_baseline(goal):
    d = r.decide(week(goal, previous=None, previous_streak=r.Streak(1)))
    assert d.outcome == r.BASELINE and d.streak == r.Streak()


# --- losing ------------------------------------------------------------------

def test_lose_2_target_reached_switches_to_maintain():
    assert r.decide(week(avg=68.4, previous=68.8)).outcome == r.TARGET_REACHED
    assert r.decide(week(avg=67.5, previous=68.0)).outcome == r.TARGET_REACHED  # went past it


def test_lose_3_too_fast_raises_150_even_while_settling_or_logs_are_bad():
    d = r.decide(week(avg=71.0, previous=71.8, settling=r.COOL_DOWN, log_coverage=0.1))  # 0.8 > 1% of 71
    assert (d.outcome, d.kcal_delta) == (r.TOO_FAST, 150)


def test_lose_4_baseline_or_cool_down_week_holds_and_resets_the_streak():
    for settling in (r.BASELINE, r.COOL_DOWN):
        d = r.decide(week(avg=72.4, previous=72.5, settling=settling, previous_streak=r.Streak(1)))
        assert d.outcome == settling and d.streak == r.Streak() and d.kcal_delta == 0


def test_lose_a_pending_change_holds_and_keeps_the_streak():
    d = r.decide(week(avg=72.4, previous=72.5, change_pending=True, previous_streak=r.Streak(1)))
    assert d.outcome == r.CHANGE_PENDING and d.streak == r.Streak(1)


def test_lose_5_at_least_half_the_expected_loss_is_on_track():
    d = r.decide(week(avg=72.27, previous=72.5, previous_streak=r.Streak(1)))  # lost 0.23 of 0.45
    assert d.outcome == r.ON_TRACK and d.streak == r.Streak()


def test_lose_6_period_week_holds_and_keeps_the_streak():
    d = r.decide(week(avg=72.4, previous=72.5, period_week=True, previous_streak=r.Streak(1)))
    assert d.outcome == r.PERIOD_WEEK and d.streak == r.Streak(1)


@pytest.mark.parametrize("coverage, kcal, outcome", [
    (0.69, 1600, r.LOGS_LOW), (None, 1600, r.LOGS_LOW), (0.8, None, r.LOGS_LOW), (0.8, 1761, r.LOGS_OVER),
])
def test_lose_7_food_logs_must_be_trusted(coverage, kcal, outcome):
    d = r.decide(week(avg=72.4, previous=72.5, log_coverage=coverage, avg_logged_kcal=kcal,
                      previous_streak=r.Streak(1)))
    assert d.outcome == outcome and d.kcal_delta == 0 and d.streak == r.Streak(1)


def test_lose_8_first_slow_or_stalled_week_waits():
    slow = r.decide(week(avg=72.29, previous=72.5))  # lost 0.21: at least 0.2, under half of 0.45
    assert (slow.outcome, slow.classification, slow.streak) == (r.WAIT, r.SLOW, r.Streak(1, False))
    stalled = r.decide(week(avg=72.6, previous=72.5))  # gained: stalled
    assert (stalled.outcome, stalled.classification, stalled.streak) == (r.WAIT, r.STALLED, r.Streak(1, True))


def test_lose_9_two_bad_weeks_cut_150_if_either_stalled_else_100():
    two_slow = r.decide(week(avg=72.29, previous=72.5, previous_streak=r.Streak(1, False)))
    assert (two_slow.outcome, two_slow.kcal_delta, two_slow.streak) == (r.LOWER, -100, r.Streak())
    stalled_now = r.decide(week(avg=72.5, previous=72.5, previous_streak=r.Streak(1, False)))
    assert stalled_now.kcal_delta == -150
    stalled_before = r.decide(week(avg=72.29, previous=72.5, previous_streak=r.Streak(1, True)))
    assert stalled_before.kcal_delta == -150


def test_lose_uses_a_default_expected_change_when_setup_gave_none():
    d = r.decide(week(avg=72.37, previous=72.5, expected_kg=None))  # 0.13 >= half of 0.25
    assert d.outcome == r.ON_TRACK


# --- gaining -----------------------------------------------------------------

def gain(avg, previous, **kw):
    return r.decide(week("gain", avg=avg, previous=previous, expected_kg=0.27, **kw))


def test_gain_2_target_reached():
    assert gain(59.6, 59.3).outcome == r.TARGET_REACHED


def test_gain_3_baseline_or_cool_down_holds():
    assert gain(55.0, 55.0, settling=r.BASELINE).outcome == r.BASELINE


def test_gain_4_more_than_half_a_kilo_is_too_fast():
    d = gain(55.6, 55.0)
    assert (d.outcome, d.kcal_delta) == (r.TOO_FAST, -100)


def test_gain_5_on_track_and_6_period():
    assert gain(55.14, 55.0).outcome == r.ON_TRACK
    assert gain(55.05, 55.0, period_week=True).outcome == r.PERIOD_WEEK


def test_gain_7_food_gate_is_eating_under_target():
    assert gain(55.05, 55.0, avg_logged_kcal=1439).outcome == r.LOGS_UNDER
    assert gain(55.05, 55.0, avg_logged_kcal=2500).outcome == r.WAIT  # eating more is fine


def test_gain_8_two_slow_weeks_raise_150():
    assert gain(55.05, 55.0).streak == r.Streak(1)
    d = gain(55.05, 55.0, previous_streak=r.Streak(1))
    assert (d.outcome, d.kcal_delta) == (r.RAISE, 150)


# --- maintaining -------------------------------------------------------------

def keep(avg, previous, **kw):
    return r.decide(week("maintain", avg=avg, previous=previous, **kw))


def test_maintain_2_baseline_holds_and_3_steady_keeps():
    assert keep(70.5, 70.0, settling=r.COOL_DOWN).outcome == r.COOL_DOWN
    d = keep(70.24, 70.0, previous_streak=r.Streak(1, False, "up"))
    assert d.outcome == r.ON_TRACK and d.streak == r.Streak()


def test_maintain_4_period_and_5_food_gate_within_ten_percent():
    assert keep(70.3, 70.0, period_week=True).outcome == r.PERIOD_WEEK
    assert keep(70.3, 70.0, avg_logged_kcal=1400).outcome == r.LOGS_OFF
    assert keep(70.3, 70.0, avg_logged_kcal=1800).outcome == r.LOGS_OFF
    assert keep(70.3, 70.0, avg_logged_kcal=1750).outcome == r.WAIT


def test_maintain_6_first_drift_waits_and_a_change_of_direction_starts_again():
    d = keep(70.3, 70.0)
    assert (d.outcome, d.streak) == (r.WAIT, r.Streak(1, False, "up"))
    d = keep(69.7, 70.0, previous_streak=r.Streak(1, False, "up"))
    assert (d.outcome, d.streak) == (r.WAIT, r.Streak(1, False, "down"))


def test_maintain_7_two_weeks_the_same_way_change_100():
    up = keep(70.3, 70.0, previous_streak=r.Streak(1, False, "up"))
    assert (up.outcome, up.kcal_delta) == (r.LOWER, -100)
    down = keep(69.7, 70.0, previous_streak=r.Streak(1, False, "down"))
    assert (down.outcome, down.kcal_delta) == (r.RAISE, 100)
