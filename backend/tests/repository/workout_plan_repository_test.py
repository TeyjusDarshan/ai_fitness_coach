"""Tests for WorkoutPlanRepository.create_progressed_session.

Supabase is faked with FakeSupabaseClient/FakeTable below rather than plain
MagicMock chains: create_progressed_session's branching (regression/
progression swaps, injury-multiplier override, min/max clamping) depends on
what each query's filters actually match, so the fake applies .eq/.in_/.ilike
filters against small per-table fixture lists instead of returning a fixed
canned response regardless of arguments.
"""
from typing import Dict, List

from backend.repository.workout_plan_repository import PainLevel, WorkoutPlanRepository
import pytest



class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, name, rows, inserted, query_log, next_id):
        self.name = name
        self.rows = rows
        self.inserted = inserted
        self.query_log = query_log
        self._next_id = next_id
        self._eq = []
        self._in = []
        self._ilike = []
        self._insert_rows = None

    def select(self, *_args, **_kwargs):
        return self

    def insert(self, rows):
        self._insert_rows = rows if isinstance(rows, list) else [rows]
        return self

    def eq(self, key, value):
        self._eq.append((key, value))
        return self

    def in_(self, key, values):
        self._in.append((key, set(values)))
        return self

    def ilike(self, key, pattern):
        self._ilike.append((key, pattern.strip("%").lower()))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        self.query_log.append(self.name)
        if self._insert_rows is not None:
            saved = []
            for row in self._insert_rows:
                row = dict(row)
                row.setdefault("id", self._next_id())
                saved.append(row)
            self.inserted.setdefault(self.name, []).extend(saved)
            self.rows.extend(saved)
            return FakeResponse(saved)

        matched = self.rows
        for key, value in self._eq:
            matched = [r for r in matched if r.get(key) == value]
        for key, values in self._in:
            matched = [r for r in matched if r.get(key) in values]
        for key, needle in self._ilike:
            matched = [r for r in matched if needle in (r.get(key) or "").lower()]
        return FakeResponse(matched)


class FakeSupabaseClient:
    """Minimal stand-in for the supabase-py Client used by WorkoutPlanRepository.

    Backing rows for a table are seeded via `.seed(...)`; reads apply
    .eq/.in_/.ilike filters against them, and inserts append a row (assigning
    an auto-incrementing id when one isn't already present) and are also
    recorded in `.inserted[table]` so tests can assert on exactly what would
    have been written.
    """

    def __init__(self):
        self.tables: Dict[str, List[dict]] = {}
        self.inserted: Dict[str, List[dict]] = {}
        self.query_log: List[str] = []
        self._id_counter = 999

    def _next_id(self):
        self._id_counter += 1
        return self._id_counter

    def seed(self, table: str, rows: List[dict]):
        self.tables.setdefault(table, []).extend(rows)

    def table(self, name: str) -> FakeTable:
        return FakeTable(
            name, self.tables.setdefault(name, []), self.inserted, self.query_log, self._next_id
        )


def _repo(client):
    return WorkoutPlanRepository(client=client)


def _row(**overrides):
    row = {
        "id": 1,
        "exercise_id": 100,
        "day_number": 1,
        "category": "primary",
        "slot_label": "Squat",
        "sets": 3,
        "reps": "10,10,10",
        "rep_range": "8-12",
        "note": "keep form tight",
        "session_exercise_rpe": None,
    }
    row.update(overrides)
    return row


def _source_session(**overrides):
    session = {"id": 55, "plan_type": "3_day", "completed_at": None}
    session.update(overrides)
    return session


def test_hard_rpe_reduces_every_set_by_one():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 6, "max_reps": 15}])
    repo = _repo(client)

    exercise_rows = [_row(reps="10,11,10", session_exercise_rpe={"rpe": 10})]

    session = repo.create_progressed_session("usr_1", _source_session(), exercise_rows)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["reps"] == "9,10,9"
    assert new_row["exercise_id"] == 100
    assert new_row["rep_range"] == "8-12"
    assert new_row["session_id"] == session["id"]


def test_missing_rpe_falls_back_to_hard():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 6, "max_reps": 15}])
    repo = _repo(client)

    exercise_rows = [_row(reps="10,10,10", session_exercise_rpe=None)]

    repo.create_progressed_session("usr_1", _source_session(), exercise_rows)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["reps"] == "9,9,9"


def test_correct_rpe_bumps_only_the_next_uncaught_up_set_by_one():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 6, "max_reps": 20}])
    repo = _repo(client)

    # Week 1: fully uniform -> set 1 (the first index at the shared minimum)
    # is the one that advances.
    week1 = repo.create_progressed_session(
        "usr_1", _source_session(), [_row(reps="10,9,9", session_exercise_rpe={"rpe": 8})]
    )
    [week1_row] = client.inserted["session_exercises"]
    assert week1_row["reps"] == "10,10,9"

    # Week 2: carries forward last week's output row -> set 2 is now the
    # first one still at the shared minimum (10), so it advances next.
    client.inserted["session_exercises"] = []
    week2_row_input = _row(id=2, reps=week1_row["reps"], session_exercise_rpe={"rpe": 8})
    repo.create_progressed_session("usr_1", _source_session(id=week1["id"]), [week2_row_input])
    [week2_row] = client.inserted["session_exercises"]
    assert week2_row["reps"] == "10,10,10"

    # Week 3: set 3 is the last one still behind -> it advances, completing
    # the lap (all three sets now equal).
    client.inserted["session_exercises"] = []
    week3_row_input = _row(id=3, reps=week2_row["reps"], session_exercise_rpe={"rpe": 8})
    repo.create_progressed_session("usr_1", _source_session(), [week3_row_input])
    [week3_row] = client.inserted["session_exercises"]
    assert week3_row["reps"] == "11,10,10"

    # Week 4: lap complete and uniform again -> set 1 starts a new lap.
    client.inserted["session_exercises"] = []
    week4_row_input = _row(id=4, reps=week3_row["reps"], session_exercise_rpe={"rpe": 8})
    repo.create_progressed_session("usr_1", _source_session(), [week4_row_input])
    [week4_row] = client.inserted["session_exercises"]
    assert week4_row["reps"] == "11,11,10"


def test_too_easy_rpe_bumps_only_the_next_uncaught_up_set_by_two():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 6, "max_reps": 25}])
    repo = _repo(client)

    exercise_rows = [_row(reps="10,10,10", session_exercise_rpe={"rpe": 6})]

    repo.create_progressed_session("usr_1", _source_session(), exercise_rows)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["reps"] == "12,10,10"


def test_reported_joint_pain_forces_hard_regardless_of_rpe_and_triggers_regression_swap():
    client = FakeSupabaseClient()
    client.seed("user_joint_pain", [{"user_id": "usr_2", "joint_id": 5, "pain_level": "moderate"}])
    client.seed("exercise_loaded_joints", [{"exercise_id": 200, "joint_id": 5, "joint_load": "high"}])
    client.seed("exercises", [
        {"id": 200, "min_reps": 6, "max_reps": 15},
        {"id": 201, "min_reps": 4, "max_reps": 10},
    ])
    client.seed("exercise_relationships", [{
        "from_exercise_id": 200, "to_exercise_id": 201, "type": "regression", "reason": "Lack of strength",
    }])
    repo = _repo(client)

    exercise_rows = [_row(
        id=2, exercise_id=200,
        reps="6,6,6",
        # A "too easy" RPE would normally push reps up, but MODERATE pain on
        # a "high" loaded joint (multiplier 0.0) must override that to hard,
        # dropping every set to 5 - below this exercise's min_reps of 6.
        session_exercise_rpe={"rpe": 6},
    )]

    session = repo.create_progressed_session("usr_2", _source_session(), exercise_rows)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["exercise_id"] == 201
    assert new_row["reps"] == "4,4,4"
    assert new_row["rep_range"] == "4-10"
    assert new_row["session_id"] == session["id"]


def test_below_min_without_regression_edge_clamps_every_set_to_own_min_reps():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 300, "min_reps": 6, "max_reps": 15}])
    repo = _repo(client)

    exercise_rows = [_row(id=3, exercise_id=300, reps="6,6,6", session_exercise_rpe={"rpe": 10})]

    repo.create_progressed_session("usr_3", _source_session(), exercise_rows)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["exercise_id"] == 300
    assert new_row["reps"] == "6,6,6"
    assert new_row["rep_range"] == "8-12"


def test_above_max_with_progression_edge_swaps_exercise():
    client = FakeSupabaseClient()
    client.seed("exercises", [
        {"id": 400, "min_reps": 8, "max_reps": 20},
        {"id": 401, "min_reps": 10, "max_reps": 18},
    ])
    client.seed("exercise_relationships", [{
        "from_exercise_id": 400, "to_exercise_id": 401, "type": "progression",
        "reason": "RIR > 3 and hit rep ceiling",
    }])
    repo = _repo(client)

    exercise_rows = [_row(
        id=4, exercise_id=400, reps="20,19,19", session_exercise_rpe={"rpe": 6},
    )]

    session = repo.create_progressed_session("usr_4", _source_session(), exercise_rows)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["exercise_id"] == 401
    assert new_row["reps"] == "10,10,10"
    assert new_row["rep_range"] == "10-18"
    assert new_row["session_id"] == session["id"]


def test_above_max_without_progression_edge_clamps_every_set_to_own_max_reps():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 500, "min_reps": 8, "max_reps": 20}])
    repo = _repo(client)

    exercise_rows = [_row(
        id=5, exercise_id=500, reps="20,19,19", session_exercise_rpe={"rpe": 6},
    )]

    repo.create_progressed_session("usr_5", _source_session(), exercise_rows)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["exercise_id"] == 500
    assert new_row["reps"] == "20,20,20"
    assert new_row["rep_range"] == "8-12"


def test_falls_back_to_generic_reason_and_skips_exercise_queries_when_no_source_exercises():
    client = FakeSupabaseClient()
    repo = _repo(client)

    source_session = {"id": 77, "plan_type": "4_day", "completed_at": None}

    session = repo.create_progressed_session("usr_6", source_session, [])

    assert client.inserted["sessions"][0]["plan_selection_reason"] == (
        "Progressive overload from the previous completed session."
    )
    assert "session_exercises" not in client.inserted
    assert set(client.query_log) == {"sessions", "user_joint_pain"}
    assert session["id"] == client.inserted["sessions"][0]["id"]


def test_fetch_user_joint_pain_parses_pain_level_enum():
    client = FakeSupabaseClient()
    client.seed("user_joint_pain", [
        {"user_id": "usr_7", "joint_id": 1, "pain_level": "severe"},
        {"user_id": "usr_7", "joint_id": 2, "pain_level": "mild"},
        {"user_id": "usr_other", "joint_id": 1, "pain_level": "moderate"},
    ])
    repo = _repo(client)

    result = repo._fetch_user_joint_pain("usr_7")

    assert result == {1: PainLevel.SEVERE, 2: PainLevel.MILD}
