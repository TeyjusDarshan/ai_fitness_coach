"""Tests for backend/cardio.py: the cardio level ladder, the weekly vote and
the medium hold."""
import pytest

from backend.cardio import (
    CARDIO_START,
    actual_work_seconds,
    cardio_day,
    estimated_seconds,
    exercise_rest_seconds,
    next_level,
    period_seconds,
    step_down,
    step_up,
    week_outcome,
)


@pytest.mark.parametrize("level, expected", [
    ((1, 30), (1, 40)),
    ((1, 50), (1, 60)),
    ((1, 55), (1, 60)),   # capped at 60
    ((1, 60), (2, 30)),   # a new round, back at 30 s
    ((2, 60), (3, 30)),
    ((1, 15), (1, 25)),
])
def test_step_up(level, expected):
    assert step_up(level) == expected


@pytest.mark.parametrize("level, expected", [
    ((1, 30), (1, 20)),
    ((1, 20), (1, 15)),   # floored at 15
    ((2, 30), (2, 20)),
    ((2, 15), (1, 60)),   # a round fewer, at 60 s
    ((3, 15), (2, 60)),
    ((1, 15), (1, 15)),   # the floor
])
def test_step_down(level, expected):
    assert step_down(level) == expected


def _done(rating):
    return {"completed_at": "2026-10-13T10:00:00+00:00", "cardio_rating": rating}


@pytest.mark.parametrize("sessions, expected", [
    ([_done("easy"), _done("easy"), _done("hard")], "easy"),
    ([_done("easy"), _done("hard")], "hard"),                      # tie -> harder
    ([_done("easy"), _done("medium")], "medium"),                  # tie -> harder
    ([_done("easy"), _done("medium"), _done("hard")], "hard"),     # three-way tie
    ([_done("easy"), _done(None)], "medium"),                      # unrated counts as medium
    # A missed (never completed) session has no vote, even if it was rated.
    ([_done("easy"), {"completed_at": None, "cardio_rating": "hard"}], "easy"),
    ([{"completed_at": None, "cardio_rating": None}], None),
    ([], None),
])
def test_week_outcome_is_the_majority_with_ties_going_harder(sessions, expected):
    assert week_outcome(sessions) == expected


def test_easy_steps_up_and_hard_steps_down():
    assert next_level((1, 30), "easy") == (1, 40)
    assert next_level((1, 30), "hard") == (1, 20)


def test_no_completed_cardio_holds():
    assert next_level((1, 40), None) == (1, 40)


def test_medium_holds_once_then_steps_up():
    assert next_level((1, 40), "medium") == (1, 40)
    assert next_level((1, 40), "medium", previous_week=("medium", (1, 40))) == (1, 50)


@pytest.mark.parametrize("previous_week", [
    ("medium", (1, 30)),   # the level changed since: hold first
    ("easy", (1, 40)),
    ("hard", (1, 40)),
    None,
])
def test_medium_holds_unless_last_week_was_medium_at_this_level(previous_week):
    assert next_level((1, 40), "medium", previous_week) == (1, 40)


@pytest.mark.parametrize("work, rest", [(30, 10), (40, 13), (50, 17), (60, 20), (15, 5), (21, 7)])
def test_the_rest_between_exercises_is_a_third_of_the_exercise(work, rest):
    assert exercise_rest_seconds(work) == rest


def test_estimated_seconds_counts_work_rests_and_round_rests():
    # 10 get-ready + 10 x 30 work + 9 x 10 rest.
    assert estimated_seconds(CARDIO_START, 10) == 10 + 300 + 90
    # Two rounds at 60 s: twice the work and 20 s rests, plus one 30 s round rest.
    assert estimated_seconds((2, 60), 10) == 10 + 2 * 600 + 2 * 9 * 20 + 30
    assert estimated_seconds((1, 30), 0) == 0


def test_cardio_day_relabels_a_rest_day():
    rest = {"day_number": 2, "day_label": "Day 2", "split_name": "Rest", "is_rest_day": True,
            "primary": [], "secondary": []}
    day = cardio_day(rest)
    assert (day["split_name"], day["is_rest_day"], day["kind"]) == ("Cardio", False, "cardio")
    assert rest["is_rest_day"] is True   # the template itself is untouched


@pytest.mark.parametrize("seconds, expected", [(30, 21), (50, 35), (60, 42), (40, 28), (20, 15), (15, 15)])
def test_a_period_day_runs_each_exercise_at_70_percent_with_a_15_second_floor(seconds, expected):
    assert period_seconds(seconds) == expected


def test_actual_work_seconds_only_scales_a_period_session():
    assert actual_work_seconds({"cardio_work_seconds": 30, "is_period": True}) == 21
    assert actual_work_seconds({"cardio_work_seconds": 30, "is_period": False}) == 30


def test_period_sessions_never_vote():
    period_easy = {**_done("easy"), "is_period": True}
    assert week_outcome([period_easy, period_easy, _done("hard")]) == "hard"
    assert week_outcome([period_easy, period_easy]) is None
