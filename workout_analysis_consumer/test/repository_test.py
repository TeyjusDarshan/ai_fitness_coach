"""Tests for the per-exercise "compared_to_last_time" the summary relies on."""
from workout_analysis_consumer.repository import _compare_to_last_time


def _exercise(name, *completed):
    return {
        "name": name,
        "set_logs": [{"set_number": i, "completed_reps": reps} for i, reps in enumerate(completed, start=1)],
    }


def test_compares_total_done_across_sets_with_the_same_exercise_last_time():
    exercises = [
        _exercise("Squat", 10, 10, 9),       # 29 vs 28
        _exercise("Row", 8, 8),              # 16 vs 18
        _exercise("Plank", 30, 30),          # 60 seconds vs 60
    ]
    previous = [_exercise("Squat", 10, 9, 9), _exercise("Row", 9, 9), _exercise("Plank", 25, 35)]

    _compare_to_last_time(exercises, previous)

    assert [e["compared_to_last_time"] for e in exercises] == ["more", "less", "same"]


def test_an_exercise_not_done_last_time_has_no_comparison():
    exercises = [_exercise("Knee push-up", 8, 8)]

    _compare_to_last_time(exercises, [_exercise("Push-up", 5, 5)])

    assert exercises[0]["compared_to_last_time"] is None


def test_no_previous_session_leaves_every_comparison_empty():
    exercises = [_exercise("Squat", 10), _exercise("Row", 8)]

    _compare_to_last_time(exercises, [])

    assert [e["compared_to_last_time"] for e in exercises] == [None, None]


def test_unlogged_sets_count_as_nothing_done():
    exercises = [_exercise("Squat", 10)]  # only one of the sets logged

    _compare_to_last_time(exercises, [_exercise("Squat", 10, 10)])

    assert exercises[0]["compared_to_last_time"] == "less"
