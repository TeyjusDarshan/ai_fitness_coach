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


# ---------- cardio sessions ----------

from workout_analysis_consumer.prompts import WORKOUT_ANALYSIS_SYSTEM_PROMPT  # noqa: E402
from workout_analysis_consumer.repository import AnalysisRepository  # noqa: E402


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *_):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def eq(self, key, value):
        self.rows = [row for row in self.rows if row.get(key) == value]
        return self

    def execute(self):
        return type("Response", (), {"data": self.rows})()


class _Client:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return _Query(list(self.tables.get(name, [])))


def _cardio_client(previous_level=(1, 30), is_period=False):
    return _Client({
        "sessions": [
            {"id": 22, "day_number": 2, "plan_id": 8, "is_period": is_period, "feedback_audio_path": None,
             "kind": "cardio", "cardio_rounds": 1, "cardio_work_seconds": 40, "cardio_rating": "hard",
             "plans": {"user_id": "usr_1", "plan_type": "3_day", "parent_plan_id": 7}},
            {"id": 12, "day_number": 2, "plan_id": 7, "is_period": False, "started_at": "s",
             "completed_at": "c", "kind": "cardio", "cardio_rounds": previous_level[0],
             "cardio_work_seconds": previous_level[1], "cardio_rating": "easy",
             "plans": {"parent_plan_id": None}, "session_exercises": []},
        ],
        "cardio_exercises": [
            {"name": "Side step", "position": 2, "active": True},
            {"name": "Marching rows", "position": 1, "active": True},
            {"name": "Retired", "position": 3, "active": False},
        ],
        "user_profiles": [{"user_id": "usr_1", "profile": {}, "name": "Meena"}],
    })


def test_a_cardio_session_carries_its_circuit_level_rating_and_comparison():
    context = AnalysisRepository(client=_cardio_client()).fetch_context(22)

    assert context["workout_type"] == "cardio"
    assert context["exercises"] == []
    assert context["cardio"] == {
        "circuit": ["Marching rows", "Side step"],
        "rounds": 1,
        "seconds_per_exercise": 40,
        "rating": "hard",
        "compared_to_last_time": "more",   # 40 s per exercise vs 30 s
    }


def test_a_cardio_comparison_counts_every_round():
    context = AnalysisRepository(client=_cardio_client(previous_level=(2, 30))).fetch_context(22)

    assert context["cardio"]["compared_to_last_time"] == "less"   # 1 x 40 vs 2 x 30


def test_the_prompt_explains_cardio_days():
    assert '"workout_type" is "cardio"' in WORKOUT_ANALYSIS_SYSTEM_PROMPT


def test_a_period_cardio_session_is_compared_by_the_seconds_she_actually_did():
    # Planned 1 x 40 s, done at 70% = 28 s, against 30 s last time.
    context = AnalysisRepository(client=_cardio_client(is_period=True)).fetch_context(22)

    assert context["cardio"]["seconds_per_exercise"] == 28
    assert context["cardio"]["compared_to_last_time"] == "less"


# ---------- clarifying-question history ----------

from workout_analysis_consumer.repository import _shape_question_history  # noqa: E402


def _round(session_id, round_number, questions, answers=None, completed_at="2026-11-10T09:00:00+00:00"):
    return {
        "session_id": session_id, "round": round_number, "questions": questions, "answers": answers or {},
        "sessions": {"day_number": 1, "scheduled_date": "2026-11-10", "completed_at": completed_at, "kind": None},
    }


def _q(qid, text, seid=None, joint=None):
    return {"id": qid, "text": text, "intent": "i", "session_exercise_id": seid, "joint": joint}


def test_question_history_groups_rounds_per_session_and_names_exercises():
    rows = [  # newest first, as fetched
        _round(30, 2, [_q("f1", "Knee enga valikkudhu?", 301, "knee")],
               {"f1": {"summary": "Inner knee.", "reply_id": 5}}),
        _round(30, 1, [_q("q1", "Squat eppadi?", 301), _q("q2", "Vera edhavadhu?")],
               {"q1": {"summary": "Knee hurt.", "reply_id": 4}}),
        _round(20, 1, [_q("q1", "Row eppadi?", 302)], completed_at=None),
    ]

    history = _shape_question_history(rows, {301: "Squat", 302: "Row"}, 8)

    assert [entry["session_id"] for entry in history] == [30, 20]
    assert history[0]["date"] == "2026-11-10"
    assert history[0]["workout_type"] == "strength"
    assert [(q["question"], q["exercise"], q["answer"], q["follow_up"]) for q in history[0]["questions"]] == [
        ("Squat eppadi?", "Squat", "Knee hurt.", False),
        ("Vera edhavadhu?", None, None, False),
        ("Knee enga valikkudhu?", "Squat", "Inner knee.", True),
    ]
    assert history[1]["date"] == "2026-11-10"  # falls back to scheduled_date


def test_question_history_keeps_only_the_newest_sessions():
    rows = [_round(session_id, 1, [_q("q1", "?")]) for session_id in range(20, 10, -1)]

    history = _shape_question_history(rows, {}, 8)

    assert [entry["session_id"] for entry in history] == list(range(20, 12, -1))
