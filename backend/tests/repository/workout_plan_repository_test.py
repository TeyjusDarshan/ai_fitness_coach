"""Tests for WorkoutPlanRepository's plan/session writes: create_plan,
create_progressed_plan, and complete_session.

Supabase is faked with FakeSupabaseClient/FakeTable below rather than plain
MagicMock chains: create_progressed_plan's branching (regression/
progression swaps, injury-multiplier override, min/max clamping) depends on
what each query's filters actually match, so the fake applies .eq/.in_/.ilike
filters against small per-table fixture lists instead of returning a fixed
canned response regardless of arguments.
"""
from datetime import date
from typing import Dict, List

from backend.repository import workout_plan_repository
from backend.repository.workout_plan_repository import (
    PainLevel,
    PlanRegenerationError,
    WorkoutPlanRepository,
    is_session_missed,
)
import pytest


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    """Pin app_today() to the Monday the fixture plans start on (2026-10-12),
    so none of their sessions count as missed unless a test moves it on."""
    set_today(monkeypatch, date(2026, 10, 12))


def set_today(monkeypatch, today):
    monkeypatch.setattr(workout_plan_repository, "app_today", lambda: today)


class FakeResponse:
    def __init__(self, data):
        self.data = data


# Column defaults the real schema fills in on insert, where a test reads the
# inserted row back through a filter on that column.
TABLE_DEFAULTS = {"plans": {"completed": False}}


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
        self._is_null = []
        self._gte = []
        self._neq = []
        self._insert_rows = None
        self._update = None
        self._delete = False

    def select(self, *_args, **_kwargs):
        return self

    def update(self, values):
        self._update = values
        return self

    def delete(self):
        self._delete = True
        return self

    def is_(self, key, value):
        assert value == "null"
        self._is_null.append(key)
        return self

    def insert(self, rows):
        self._insert_rows = rows if isinstance(rows, list) else [rows]
        return self

    def eq(self, key, value):
        self._eq.append((key, value))
        return self

    def neq(self, key, value):
        self._neq.append((key, value))
        return self

    def gte(self, key, value):
        self._gte.append((key, value))
        return self

    def in_(self, key, values):
        self._in.append((key, set(values)))
        return self

    def upsert(self, row, on_conflict, ignore_duplicates=False):
        keys = on_conflict.split(",")
        existing = [r for r in self.rows if all(r.get(k) == row[k] for k in keys)]
        if existing:
            # Like PostgREST: ignore the row, or merge just its columns in.
            if not ignore_duplicates:
                existing[0].update(row)
            self._insert_rows = []
        else:
            self._insert_rows = [row]
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
                row = {**TABLE_DEFAULTS.get(self.name, {}), **row}
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
        for key in self._is_null:
            matched = [r for r in matched if r.get(key) is None]
        for key, value in self._neq:
            matched = [r for r in matched if r.get(key) != value]
        for key, value in self._gte:
            matched = [r for r in matched if r.get(key) is not None and r[key] >= value]
        if self._update is not None:
            for r in matched:
                r.update(self._update)
        if self._delete:
            # No cascade: child rows stay, as nothing reads them back here.
            self.rows[:] = [r for r in self.rows if not any(r is m for m in matched)]
            self.query_log.append(f"delete:{self.name}")
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


def _source_plan(**overrides):
    plan = {"id": 55, "plan_type": "3_day", "completed_at": None}
    plan.update(overrides)
    return plan


def _progress(repo, user_id, source_plan, exercise_rows, missed_days=(), period_days=()):
    """create_progressed_plan with the source plan's sessions built from
    exercise_rows: one session per distinct day_number, each scheduled on
    2026-10-12 + (day_number - 1) with its rows nested. Every session is
    completed except those whose day_number is in missed_days."""
    sessions = {}
    for row in exercise_rows:
        day_number = row["day_number"]
        session = sessions.setdefault(day_number, {
            "id": 500 + day_number,
            "day_number": day_number,
            "scheduled_date": date(2026, 10, 11 + day_number).isoformat(),
            "completed_at": None if day_number in missed_days else "2026-10-12T10:30:00+00:00",
            "is_period": day_number in period_days,
            "session_exercises": [],
        })
        session["session_exercises"].append({k: v for k, v in row.items() if k != "day_number"})
    return repo.create_progressed_plan(user_id, source_plan, list(sessions.values()))


def _hit(reps):
    """Set logs completing every set at exactly its target reps."""
    return [{"set_number": i, "completed_reps": int(r)} for i, r in enumerate(reps.split(","), start=1)]


def _after_streak(client, source_plan, previous_rows, parent_id=54, missed_days=(), period_days=()):
    """Seed the previous week's plan (parent_id) with previous_rows nested
    under one session per day, and return source_plan pointing at it, so
    create_progressed_plan sees a prior week to compare against."""
    sessions = {}
    for row in previous_rows:
        day_number = row["day_number"]
        session = sessions.setdefault(day_number, {
            "id": 400 + day_number,
            "plan_id": parent_id,
            "day_number": day_number,
            "scheduled_date": date(2026, 10, 4 + day_number).isoformat(),
            "completed_at": None if day_number in missed_days else "2026-10-05T10:30:00+00:00",
            "is_period": day_number in period_days,
            "session_exercises": [],
        })
        session["session_exercises"].append({k: v for k, v in row.items() if k != "day_number"})
    client.seed("sessions", list(sessions.values()))
    return {**source_plan, "parent_plan_id": parent_id}


def test_hard_rpe_reduces_every_set_by_one():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 6, "max_reps": 15}])
    repo = _repo(client)

    exercise_rows = [_row(reps="10,11,10", session_exercise_rpe={"rpe": 10})]

    _progress(repo, "usr_1", _source_plan(), exercise_rows)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["reps"] == "9,10,9"
    assert new_row["exercise_id"] == 100
    assert new_row["rep_range"] == "8-12"
    assert new_row["session_id"] == client.inserted["sessions"][0]["id"]


def test_missing_rpe_falls_back_to_hard():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 6, "max_reps": 15}])
    repo = _repo(client)

    exercise_rows = [_row(reps="10,10,10", session_exercise_rpe=None)]

    _progress(repo, "usr_1", _source_plan(), exercise_rows)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["reps"] == "9,9,9"


def test_missing_rpe_with_every_set_hit_counts_as_correct_not_hard():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 6, "max_reps": 20}])
    repo = _repo(client)

    previous = [_row(id=1, reps="10,9,9", session_exercise_set_logs=_hit("10,9,9"))]
    source = _after_streak(client, _source_plan(), previous)
    this_week = [_row(id=2, reps="10,9,9", session_exercise_rpe=None,
                      session_exercise_set_logs=_hit("10,9,9"))]

    _progress(repo, "usr_1", source, this_week)

    [new_row] = client.inserted["session_exercises"]
    # Same as a logged RPE 8 after a two-week streak: the ramp advances by 1.
    assert new_row["reps"] == "10,10,9"


def test_missing_rpe_with_every_set_hit_but_no_streak_is_copied():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 6, "max_reps": 20}])
    repo = _repo(client)

    this_week = [_row(reps="10,10,10", session_exercise_rpe=None, session_exercise_set_logs=_hit("10,10,10"))]

    _progress(repo, "usr_1", _source_plan(), this_week)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["reps"] == "10,10,10"


def test_missing_rpe_with_a_set_short_is_hard_from_performed_reps():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 6, "max_reps": 20}])
    repo = _repo(client)

    this_week = [_row(reps="10,10,10", session_exercise_rpe=None, session_exercise_set_logs=_hit("10,10,8"))]

    _progress(repo, "usr_1", _source_plan(), this_week)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["reps"] == "9,9,7"


def test_correct_rpe_bumps_only_the_next_uncaught_up_set_by_one_after_two_weeks_at_target():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 6, "max_reps": 20}])
    repo = _repo(client)

    previous = [_row(id=1, reps="10,9,9", session_exercise_set_logs=_hit("10,9,9"))]
    source = _after_streak(client, _source_plan(), previous)
    this_week = [_row(id=2, reps="10,9,9", session_exercise_rpe={"rpe": 8},
                      session_exercise_set_logs=_hit("10,9,9"))]

    _progress(repo, "usr_1", source, this_week)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["reps"] == "10,10,9"


def test_easy_rpe_bumps_without_a_two_week_streak():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 6, "max_reps": 20}])
    repo = _repo(client)

    this_week = [_row(reps="10,9,9", session_exercise_rpe={"rpe": 6}, session_exercise_set_logs=_hit("10,9,9"))]

    _progress(repo, "usr_1", _source_plan(), this_week)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["reps"] == "10,11,9"


def test_correct_rpe_without_a_streak_is_copied_forward():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 6, "max_reps": 20}])
    repo = _repo(client)

    this_week = [_row(reps="10,9,9", session_exercise_rpe={"rpe": 8}, session_exercise_set_logs=_hit("10,9,9"))]

    _progress(repo, "usr_1", _source_plan(), this_week)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["reps"] == "10,9,9"


def test_easy_rpe_bumps_even_when_last_week_fell_short():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 6, "max_reps": 20}])
    repo = _repo(client)

    previous = [_row(id=1, reps="10,9,9", session_exercise_set_logs=_hit("10,9,7"))]
    source = _after_streak(client, _source_plan(), previous)
    this_week = [_row(id=2, reps="10,9,9", session_exercise_rpe={"rpe": 6},
                      session_exercise_set_logs=_hit("10,9,9"))]

    _progress(repo, "usr_1", source, this_week)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["reps"] == "10,11,9"


@pytest.mark.parametrize("previous_reps, previous_logs, this_logs, previous_missed", [
    ("10,9,9", "10,9,8", "10,9,9", False),    # last week fell short of target
    ("9,9,9", "9,9,9", "10,9,9", False),      # targets changed since last week: streak restarts
    ("10,9,9", "10,9,9", "10,9,9", True),     # last week missed, and no completed week before it
])
def test_no_two_week_streak_copies_targets_forward(previous_reps, previous_logs, this_logs, previous_missed):
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 6, "max_reps": 20}])
    repo = _repo(client)

    previous = [_row(id=1, reps=previous_reps, session_exercise_set_logs=_hit(previous_logs))]
    source = _after_streak(client, _source_plan(), previous, missed_days={1} if previous_missed else ())
    this_week = [_row(id=2, reps="10,9,9", session_exercise_rpe={"rpe": 8},
                      session_exercise_set_logs=_hit(this_logs))]

    _progress(repo, "usr_1", source, this_week)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["reps"] == "10,9,9"


def test_hard_rpe_drops_one_from_the_reps_actually_performed():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 6, "max_reps": 15}])
    repo = _repo(client)

    exercise_rows = [_row(reps="12,12,12", session_exercise_rpe={"rpe": 10},
                          session_exercise_set_logs=_hit("12,10,9"))]

    _progress(repo, "usr_1", _source_plan(), exercise_rows)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["reps"] == "11,9,8"


@pytest.mark.parametrize("rpe", [6, 8])
@pytest.mark.parametrize("logs, expected", [
    ("10,9,8", "9,8,7"),   # last set fell short
    ("10,9", "9,8,8"),     # set 3 never logged: falls back to its target
])
def test_falling_short_of_any_set_drops_one_from_performed_reps_whatever_the_rpe(rpe, logs, expected):
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 6, "max_reps": 20}])
    repo = _repo(client)

    previous = [_row(id=1, reps="10,9,9", session_exercise_set_logs=_hit("10,9,9"))]
    source = _after_streak(client, _source_plan(), previous)
    this_week = [_row(id=2, reps="10,9,9", session_exercise_rpe={"rpe": rpe},
                      session_exercise_set_logs=_hit(logs))]

    _progress(repo, "usr_1", source, this_week)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["reps"] == expected


def test_performed_reps_below_min_swap_to_the_regression_at_its_max_reps():
    client = FakeSupabaseClient()
    client.seed("exercises", [
        {"id": 100, "min_reps": 8, "max_reps": 15},
        {"id": 101, "min_reps": 5, "max_reps": 12},
    ])
    client.seed("exercise_relationships", [{
        "from_exercise_id": 100, "to_exercise_id": 101, "type": "regression", "reason": "Lack of strength",
    }])
    repo = _repo(client)

    exercise_rows = [_row(reps="10,10,10", session_exercise_rpe={"rpe": 8},
                          session_exercise_set_logs=_hit("10,9,8"))]  # -> 9,8,7: 7 < min 8

    _progress(repo, "usr_1", _source_plan(), exercise_rows)

    [new_row] = client.inserted["session_exercises"]
    assert (new_row["exercise_id"], new_row["reps"], new_row["rep_range"]) == (101, "12,12,12", "5-12")


def test_swapped_in_exercise_has_no_streak_to_progress_from():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 6, "max_reps": 20}, {"id": 101, "min_reps": 6, "max_reps": 20}])
    repo = _repo(client)

    previous = [_row(id=1, exercise_id=101, reps="10,10,10", session_exercise_set_logs=_hit("10,10,10"))]
    source = _after_streak(client, _source_plan(), previous)
    this_week = [_row(id=2, exercise_id=100, reps="10,10,10", session_exercise_rpe={"rpe": 8},
                      session_exercise_set_logs=_hit("10,10,10"))]

    _progress(repo, "usr_1", source, this_week)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["reps"] == "10,10,10"


def test_too_easy_rpe_bumps_only_the_next_uncaught_up_set_by_two():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 6, "max_reps": 25}])
    repo = _repo(client)

    previous = [_row(id=1, reps="10,10,10", session_exercise_set_logs=_hit("10,10,10"))]
    source = _after_streak(client, _source_plan(), previous)
    exercise_rows = [_row(id=2, reps="10,10,10", session_exercise_rpe={"rpe": 6},
                          session_exercise_set_logs=_hit("10,10,10"))]

    _progress(repo, "usr_1", source, exercise_rows)

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
        session_exercise_set_logs=_hit("6,6,6"),
    )]

    plan = _progress(repo, "usr_2", _source_plan(), exercise_rows)

    [new_row] = client.inserted["session_exercises"]
    # The regression starts at the top of its own range.
    assert new_row["exercise_id"] == 201
    assert new_row["reps"] == "10,10,10"
    assert new_row["rep_range"] == "4-10"
    assert new_row["session_id"] == client.inserted["sessions"][0]["id"]


def test_below_min_without_regression_edge_clamps_every_set_to_own_min_reps():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 300, "min_reps": 6, "max_reps": 15}])
    repo = _repo(client)

    exercise_rows = [_row(id=3, exercise_id=300, reps="6,6,6", session_exercise_rpe={"rpe": 10})]

    _progress(repo, "usr_3", _source_plan(), exercise_rows)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["exercise_id"] == 300
    assert new_row["reps"] == "6,6,6"
    assert new_row["rep_range"] == "8-12"


def _progression_edge_client():
    client = FakeSupabaseClient()
    client.seed("exercises", [
        {"id": 400, "min_reps": 8, "max_reps": 20},
        {"id": 401, "min_reps": 10, "max_reps": 18},
    ])
    client.seed("exercise_relationships", [{
        "from_exercise_id": 400, "to_exercise_id": 401, "type": "progression",
        "reason": "RIR > 3 and hit rep ceiling",
    }])
    return client


def _progress_easy(client, user_id, exercise_id, reps):
    """Two weeks hitting `reps` on exercise_id, rated easy (+2 on the next set)."""
    previous = [_row(id=1, exercise_id=exercise_id, reps=reps, session_exercise_set_logs=_hit(reps))]
    source = _after_streak(client, _source_plan(), previous)
    exercise_rows = [_row(
        id=4, exercise_id=exercise_id, reps=reps, session_exercise_rpe={"rpe": 6},
        session_exercise_set_logs=_hit(reps),
    )]
    _progress(_repo(client), user_id, source, exercise_rows)
    [new_row] = client.inserted["session_exercises"]
    return new_row


def _progress_rated(client, user_id, exercise_id, reps, rpe=6):
    """Two weeks hitting `reps` on exercise_id, then rated `rpe`."""
    previous = [_row(id=1, exercise_id=exercise_id, reps=reps, session_exercise_set_logs=_hit(reps))]
    source = _after_streak(client, _source_plan(), previous)
    exercise_rows = [_row(
        id=4, exercise_id=exercise_id, reps=reps, session_exercise_rpe={"rpe": rpe},
        session_exercise_set_logs=_hit(reps),
    )]
    _progress(_repo(client), user_id, source, exercise_rows)
    [new_row] = client.inserted["session_exercises"]
    return new_row


@pytest.mark.parametrize("reps, expected", [
    ("20,19,19", "20,20,19"),   # 19 + 2 would be 21: capped at the max of 20
    ("20,20,19", "20,20,20"),   # last set reaches the max: still the same exercise
])
def test_going_up_caps_each_set_at_max_reps(reps, expected):
    client = _progression_edge_client()

    new_row = _progress_easy(client, "usr_4", 400, reps)

    assert new_row["exercise_id"] == 400
    assert new_row["reps"] == expected
    assert new_row["rep_range"] == "8-12"


@pytest.mark.parametrize("rpe", [6, 8])
def test_every_set_at_max_and_another_increase_swaps_to_the_progression(rpe):
    client = _progression_edge_client()

    new_row = _progress_rated(client, "usr_4", 400, "20,20,20", rpe=rpe)

    assert new_row["exercise_id"] == 401
    assert new_row["reps"] == "10,10,10"
    assert new_row["rep_range"] == "10-18"
    assert new_row["session_id"] == client.inserted["sessions"][0]["id"]


def test_every_set_at_max_without_a_streak_holds_on_correct_rpe():
    client = _progression_edge_client()
    rows = [_row(exercise_id=400, reps="20,20,20", session_exercise_rpe={"rpe": 8},
                 session_exercise_set_logs=_hit("20,20,20"))]

    _progress(_repo(client), "usr_4", _source_plan(), rows)

    [new_row] = client.inserted["session_exercises"]
    assert (new_row["exercise_id"], new_row["reps"]) == (400, "20,20,20")


@pytest.mark.parametrize("reps, expected", [
    ("20,19,19", "20,20,19"),   # the bumped set is capped; the others aren't lifted
    ("20,20,20", "20,20,20"),   # every set at max: nothing to progress to, stays there
])
def test_without_progression_edge_each_set_is_capped_at_its_max_reps(reps, expected):
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 500, "min_reps": 8, "max_reps": 20}])

    new_row = _progress_easy(client, "usr_5", 500, reps)

    assert new_row["exercise_id"] == 500
    assert new_row["reps"] == expected


def test_targets_already_over_max_are_capped_and_not_swapped_on_a_hard_week():
    client = _progression_edge_client()
    rows = [_row(exercise_id=400, reps="22,22,22", session_exercise_rpe={"rpe": 10},
                 session_exercise_set_logs=_hit("22,22,22"))]

    _progress(_repo(client), "usr_4", _source_plan(), rows)

    [new_row] = client.inserted["session_exercises"]
    assert (new_row["exercise_id"], new_row["reps"]) == (400, "20,20,20")


def test_falls_back_to_generic_reason_and_skips_exercise_queries_when_no_source_sessions():
    client = FakeSupabaseClient()
    repo = _repo(client)

    source_plan = {"id": 77, "plan_type": "4_day", "completed_at": None}

    plan = _progress(repo, "usr_6", source_plan, [])

    assert client.inserted["plans"][0]["plan_selection_reason"] == (
        "Progressive overload from the previous completed plan."
    )
    assert client.inserted["plans"][0]["parent_plan_id"] == 77
    assert "session_exercises" not in client.inserted
    assert "sessions" not in client.inserted
    assert set(client.query_log) == {"plans", "user_joint_pain"}
    assert plan["id"] == client.inserted["plans"][0]["id"]


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


def test_create_plan_schedules_one_session_per_training_day_from_start_date():
    from agents.prompts_v1 import DAY_TEMPLATES

    client = FakeSupabaseClient()
    repo = _repo(client)
    schedule = [
        {**day, "primary": [{"exercise_id": 100, "slot": "Hinge", "sets": 3, "reps": "10"}], "secondary": []}
        if not day["is_rest_day"] else day
        for day in DAY_TEMPLATES["3_day"]["schedule"]
    ]

    plan = repo.create_plan("usr_1", {"plan_type": "3_day", "schedule": schedule}, date(2026, 10, 13))

    assert client.inserted["plans"][0]["parent_plan_id"] is None
    sessions = client.inserted["sessions"]
    assert [(s["plan_id"], s["day_number"], s["scheduled_date"], s["kind"]) for s in sessions] == [
        (plan["id"], 1, "2026-10-13", "strength"),
        (plan["id"], 2, "2026-10-14", "cardio"),
        (plan["id"], 3, "2026-10-15", "strength"),
        (plan["id"], 4, "2026-10-16", "cardio"),
        (plan["id"], 5, "2026-10-17", "strength"),
        (plan["id"], 6, "2026-10-18", "cardio"),
    ]
    session_ids = [s["id"] for s in sessions if s["kind"] == "strength"]
    assert [row["session_id"] for row in client.inserted["session_exercises"]] == session_ids
    assert all("day_number" not in row for row in client.inserted["session_exercises"])


def test_progressed_plan_schedules_each_day_a_week_later_and_keeps_exercises_on_their_day():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 6, "max_reps": 15}])
    repo = _repo(client)

    exercise_rows = [
        _row(id=1, day_number=1, session_exercise_rpe={"rpe": 8}),
        _row(id=2, day_number=3, session_exercise_rpe={"rpe": 8}),
        _row(id=3, day_number=3, category="secondary", session_exercise_rpe={"rpe": 8}),
    ]

    plan = _progress(repo, "usr_1", _source_plan(), exercise_rows)

    sessions = {s["day_number"]: s for s in client.inserted["sessions"]}
    # Source day 1 was 2026-10-12 and day 3 was 2026-10-14 (see _progress).
    assert sessions[1]["scheduled_date"] == "2026-10-19"
    assert sessions[3]["scheduled_date"] == "2026-10-21"
    assert all(s["plan_id"] == plan["id"] for s in sessions.values())
    assert [row["session_id"] for row in client.inserted["session_exercises"]] == [
        sessions[1]["id"], sessions[3]["id"], sessions[3]["id"],
    ]


def _seed_plan_with_sessions(client, day3_completed_at=None, plan_completed=False):
    plan_ref = {"user_id": "usr_1", "plan_type": "3_day", "completed": plan_completed}
    client.seed("plans", [{"id": 7, "user_id": "usr_1", "plan_type": "3_day", "completed": plan_completed}])
    client.seed("sessions", [
        {"id": 1, "plan_id": 7, "day_number": 1, "scheduled_date": "2026-10-12",
         "started_at": "2026-10-12T10:00:00+00:00", "completed_at": "2026-10-12T10:30:00+00:00",
         "plans": plan_ref},
        {"id": 3, "plan_id": 7, "day_number": 3, "scheduled_date": "2026-10-14",
         "started_at": "2026-10-14T10:00:00+00:00", "completed_at": day3_completed_at, "plans": plan_ref},
        {"id": 5, "plan_id": 7, "day_number": 5, "scheduled_date": "2026-10-16",
         "started_at": "2026-10-16T10:00:00+00:00", "completed_at": None, "plans": plan_ref},
    ])
    client.seed("session_exercises", [
        {"id": 90, "session_id": 5, "sets": 3, "session_exercise_set_logs": [{"set_number": 1}, {"set_number": 2}]},
        {"id": 91, "session_id": 5, "sets": 2, "session_exercise_set_logs": [{"set_number": 1}, {"set_number": 2}]},
    ])


def test_complete_session_completes_the_plan_once_every_session_is_done():
    client = FakeSupabaseClient()
    _seed_plan_with_sessions(client, day3_completed_at="2026-10-14T10:40:00+00:00")
    repo = _repo(client)

    summary = repo.complete_session(5)

    assert summary["session_id"] == 5
    assert summary["day_number"] == 5
    assert (summary["exercises_completed"], summary["total_exercises"]) == (1, 2)
    assert (summary["sets_completed"], summary["total_sets"]) == (4, 5)
    assert summary["plan_completed"] is True
    assert client.tables["plans"][0]["completed"] is True
    assert client.tables["sessions"][2]["completed_at"] is not None


def test_complete_session_leaves_the_plan_open_while_other_sessions_remain():
    client = FakeSupabaseClient()
    _seed_plan_with_sessions(client, day3_completed_at=None)
    repo = _repo(client)

    summary = repo.complete_session(5)

    assert summary["plan_completed"] is False
    assert client.tables["plans"][0]["completed"] is False


def test_complete_session_does_not_recomplete_an_already_completed_plan():
    client = FakeSupabaseClient()
    _seed_plan_with_sessions(client, day3_completed_at="2026-10-14T10:40:00+00:00", plan_completed=True)
    repo = _repo(client)

    assert repo.complete_session(5)["plan_completed"] is False
    assert "plans" not in client.inserted


def test_complete_session_is_new_only_the_first_time():
    client = FakeSupabaseClient()
    _seed_plan_with_sessions(client, day3_completed_at=None)
    repo = _repo(client)

    assert repo.complete_session(5)["newly_completed"] is True
    assert repo.complete_session(5)["newly_completed"] is False


def test_complete_session_unknown_session_returns_none():
    assert _repo(FakeSupabaseClient()).complete_session(404) is None


def test_start_session_stamps_started_at_only_once():
    client = FakeSupabaseClient()
    client.seed("sessions", [{"id": 3, "plan_id": 7, "day_number": 3, "started_at": None, "completed_at": None}])
    repo = _repo(client)

    first = repo.start_session(3)["started_at"]
    assert first is not None

    client.tables["sessions"][0]["started_at"] = "2026-10-14T10:00:00+00:00"
    assert repo.start_session(3)["started_at"] == "2026-10-14T10:00:00+00:00"



def test_exercise_voice_note_path_is_found_only_within_its_session():
    client = FakeSupabaseClient()
    client.seed("session_exercises", [{"id": 51, "session_id": 5, "feedback_audio_path": None}])
    repo = _repo(client)

    assert repo.get_session_exercise(51, session_id=6) is None
    repo.set_exercise_feedback_audio_path(51, "session_5_exercise_51.webm")

    assert repo.get_session_exercise(51, session_id=5)["feedback_audio_path"] == "session_5_exercise_51.webm"
    assert repo.get_session_exercise(51)["session_id"] == 5


def test_exercise_entry_says_whether_it_has_a_voice_note():
    with_note = _row(exercises={"id": 100, "name": "Squat"}, feedback_audio_path="session_5_exercise_51.webm")
    without = _row(exercises={"id": 100, "name": "Squat"})

    assert WorkoutPlanRepository._exercise_entry(with_note)["has_feedback"] is True
    assert WorkoutPlanRepository._exercise_entry(without)["has_feedback"] is False

# --- missed sessions -----------------------------------------------------------

@pytest.mark.parametrize("scheduled_date, completed_at, missed", [
    ("2026-10-12", None, False),                         # today: still doable
    ("2026-10-11", None, True),                          # yesterday, never done
    ("2026-10-11", "2026-10-11T10:30:00+00:00", False),  # yesterday, completed
    ("2026-10-13", None, False),                         # not yet open
])
def test_is_session_missed(scheduled_date, completed_at, missed):
    session = {"scheduled_date": scheduled_date, "completed_at": completed_at, "started_at": "x"}
    assert is_session_missed(session, date(2026, 10, 12)) is missed


def test_missed_session_carries_its_exercises_forward_unchanged():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 6, "max_reps": 15}])
    repo = _repo(client)

    exercise_rows = [
        # Partial logs and no RPE: would fall back to hard (-1) if completed.
        _row(id=1, day_number=1, reps="10,11,10", session_exercise_rpe=None,
             session_exercise_set_logs=[{"set_number": 1, "completed_reps": 10}]),
        _row(id=2, day_number=3, reps="10,10,10", session_exercise_rpe={"rpe": 8},
             session_exercise_set_logs=_hit("10,10,10")),
    ]

    _progress(repo, "usr_1", _source_plan(), exercise_rows, missed_days={1})

    missed_row, done_row = client.inserted["session_exercises"]
    assert (missed_row["exercise_id"], missed_row["reps"], missed_row["rep_range"]) == (100, "10,11,10", "8-12")
    # Completed on-target with RPE 8, but with no previous week to confirm a
    # two-week streak, so it is copied rather than bumped.
    assert done_row["reps"] == "10,10,10"


def test_missed_session_with_joint_pain_still_reduces_reps():
    client = FakeSupabaseClient()
    client.seed("user_joint_pain", [{"user_id": "usr_2", "joint_id": 5, "pain_level": "mild"}])
    client.seed("exercise_loaded_joints", [{"exercise_id": 100, "joint_id": 5, "joint_load": "high"}])
    client.seed("exercises", [{"id": 100, "min_reps": 6, "max_reps": 15}])
    repo = _repo(client)

    _progress(repo, "usr_2", _source_plan(), [_row(reps="10,10,10")], missed_days={1})

    [new_row] = client.inserted["session_exercises"]
    assert new_row["reps"] == "9,9,9"


def test_progressed_plan_starts_today_when_a_week_later_has_already_passed(monkeypatch):
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 6, "max_reps": 15}])
    repo = _repo(client)
    set_today(monkeypatch, date(2026, 10, 30))

    _progress(repo, "usr_1", _source_plan(), [_row(id=1, day_number=1), _row(id=2, day_number=3)])

    sessions = {s["day_number"]: s["scheduled_date"] for s in client.inserted["sessions"]}
    # Days 2/4/6 are the 3_day cardio days, added since the source had none.
    assert sessions == {
        1: "2026-10-30", 2: "2026-10-31", 3: "2026-11-01", 4: "2026-11-02", 6: "2026-11-04",
    }


def _seed_unfinished_plan(client, day_completed_at):
    """Plan 7 (3_day, starting Mon 2026-10-12) for usr_1, with each training
    day's completed_at taken from day_completed_at."""
    client.seed("plans", [{
        "id": 7, "user_id": "usr_1", "plan_type": "3_day", "completed": False, "completed_at": None,
        "plan_selection_reason": None, "medical_clearance_warning": None,
        "coach_notes": None, "safety_summary": None,
    }])
    client.seed("exercises", [{"id": 100, "min_reps": 6, "max_reps": 15}])
    client.seed("sessions", [
        {"id": 10 + day, "plan_id": 7, "day_number": day,
         "scheduled_date": date(2026, 10, 11 + day).isoformat(),
         "started_at": None, "completed_at": completed_at,
         "session_exercises": [_row(id=100 + day, reps="10,10,10", session_exercise_rpe={"rpe": 8},
                                    session_exercise_set_logs=_hit("10,10,10"),
                                    exercises={"id": 100, "name": "Squat"})]}
        for day, completed_at in day_completed_at.items()
    ])


def test_get_unfinished_plan_closes_and_progresses_a_plan_whose_sessions_are_all_resolved(monkeypatch):
    client = FakeSupabaseClient()
    _seed_unfinished_plan(client, {1: "2026-10-12T10:30:00+00:00", 3: None, 5: None})
    repo = _repo(client)
    set_today(monkeypatch, date(2026, 10, 17))  # day 5 (Fri 16th) has passed

    result = repo.get_unfinished_plan("usr_1")

    assert client.tables["plans"][0]["completed"] is True
    [new_plan] = client.inserted["plans"]
    assert new_plan["parent_plan_id"] == 7
    assert result["id"] == new_plan["id"]
    reps_by_day = {
        s["day_number"]: row["reps"]
        for s in client.inserted["sessions"]
        for row in client.inserted["session_exercises"] if row["session_id"] == s["id"]
    }
    # No previous week on record, so nothing has held its target two weeks yet.
    assert reps_by_day == {1: "10,10,10", 3: "10,10,10", 5: "10,10,10"}


def test_get_unfinished_plan_leaves_a_plan_open_while_a_session_is_still_due(monkeypatch):
    client = FakeSupabaseClient()
    _seed_unfinished_plan(client, {1: "2026-10-12T10:30:00+00:00", 3: None, 5: None})
    repo = _repo(client)
    set_today(monkeypatch, date(2026, 10, 16))  # day 5 is today

    result = repo.get_unfinished_plan("usr_1")

    assert result["id"] == 7
    assert client.tables["plans"][0]["completed"] is False
    assert "plans" not in client.inserted


def test_mark_plan_completed_only_progresses_once():
    client = FakeSupabaseClient()
    _seed_unfinished_plan(client, {1: "2026-10-12T10:30:00+00:00"})
    repo = _repo(client)

    assert repo.mark_plan_completed(7) is not None
    assert repo.mark_plan_completed(7) is None
    assert len(client.inserted["plans"]) == 1


def test_complete_session_completes_the_plan_when_the_other_sessions_were_missed(monkeypatch):
    client = FakeSupabaseClient()
    _seed_plan_with_sessions(client, day3_completed_at=None)
    repo = _repo(client)
    set_today(monkeypatch, date(2026, 10, 16))  # day 3 (14th) was missed

    assert repo.complete_session(5)["plan_completed"] is True
    assert client.tables["plans"][0]["completed"] is True


# --- dashboard workouts ---------------------------------------------------------

def test_unfinished_plan_lists_its_workouts_in_date_order_with_names_and_exercises():
    client = FakeSupabaseClient()
    _seed_unfinished_plan(client, {5: None, 1: "2026-10-12T10:30:00+00:00", 3: None})
    secondary = _row(id=90, category="secondary", exercises={"id": 101, "name": "Plank"})
    client.tables["sessions"][0]["session_exercises"].insert(0, secondary)  # day 5
    repo = _repo(client)

    workouts = repo.get_unfinished_plan("usr_1")["workouts"]

    assert [(w["session_id"], w["day_number"], w["name"], w["scheduled_date"]) for w in workouts] == [
        (11, 1, "Full Body", "2026-10-12"),
        (13, 3, "Full Body", "2026-10-14"),
        (15, 5, "Full Body (Unilateral & Work Capacity)", "2026-10-16"),
    ]
    assert workouts[0]["completed_at"] == "2026-10-12T10:30:00+00:00"
    assert [(e["name"], e["category"]) for e in workouts[2]["exercises"]] == [
        ("Squat", "primary"), ("Plank", "secondary"),
    ]


def test_previous_plan_workouts_come_from_the_last_completed_plan_other_than_the_current_one():
    client = FakeSupabaseClient()
    _seed_unfinished_plan(client, {1: "2026-10-12T10:30:00+00:00"})
    client.tables["plans"][0]["completed"] = True
    repo = _repo(client)

    assert [w["session_id"] for w in repo.get_previous_plan_workouts("usr_1", before_plan_id=8)] == [11]
    assert repo.get_previous_plan_workouts("usr_1", before_plan_id=7) == []


def test_upsert_user_profile_writes_name_only_when_given():
    client = FakeSupabaseClient()
    upserts = []
    client.table = lambda name: _RecordingUpsert(upserts)
    repo = _repo(client)

    repo.upsert_user_profile("usr_1", {"goals": {}}, "Asha")
    repo.upsert_user_profile("usr_1", {"goals": {}})

    assert upserts[0]["name"] == "Asha"
    assert "name" not in upserts[1]


class _RecordingUpsert:
    def __init__(self, upserts):
        self.upserts = upserts

    def upsert(self, row, **_kwargs):
        self.upserts.append(row)
        return self

    def execute(self):
        return FakeResponse([self.upserts[-1]])


# --- period sessions -----------------------------------------------------------

def _seed_period_session(client, reps="10,10,10", started_at=None, exercise_id=100):
    client.seed("sessions", [{"id": 5, "plan_id": 7, "day_number": 1, "started_at": started_at, "is_period": False}])
    client.seed("session_exercises", [{
        "id": 50, "session_id": 5, "exercise_id": exercise_id, "sets": 3, "reps": reps, "rep_range": "8-12",
    }])
    return client.tables["session_exercises"][0]


def test_period_start_scales_every_set_to_70_percent_rounded_half_up():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 4, "max_reps": 15}])
    row = _seed_period_session(client, reps="11,10,9")

    session = _repo(client).start_session(5, is_period=True)

    assert row["reps"] == "8,7,6"  # 7.7, 7.0, 6.3
    assert row["exercise_id"] == 100
    assert session["is_period"] is True
    assert client.tables["sessions"][0]["is_period"] is True


def _seed_owned_period_session(client, user_id="usr_1"):
    row = _seed_period_session(client)
    client.tables["sessions"][0]["plans"] = {"user_id": user_id, "plan_type": "3_day", "completed": False}
    return row


def test_period_start_logs_todays_date_for_the_user():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 4, "max_reps": 15}])
    _seed_owned_period_session(client)

    _repo(client).start_session(5, is_period=True)

    assert client.inserted["user_period_logs"] == [
        {"user_id": "usr_1", "logged_on": "2026-10-12", "session_id": 5, "id": client.inserted["user_period_logs"][0]["id"]}
    ]


def test_a_second_period_yes_on_the_same_day_is_logged_once():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 4, "max_reps": 15}])
    _seed_owned_period_session(client)
    client.seed("user_period_logs", [{"user_id": "usr_1", "logged_on": "2026-10-12", "session_id": 4}])

    _repo(client).start_session(5, is_period=True)

    assert client.inserted.get("user_period_logs", []) == []


def test_ordinary_start_and_resumed_start_log_nothing():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 4, "max_reps": 15}])
    _seed_owned_period_session(client)
    repo = _repo(client)

    repo.start_session(5)
    repo.start_session(5, is_period=True)  # already started

    assert "user_period_logs" not in client.inserted


def test_period_start_below_min_reps_swaps_to_the_lack_of_strength_regression():
    client = FakeSupabaseClient()
    client.seed("exercises", [
        {"id": 100, "min_reps": 8, "max_reps": 15},
        {"id": 101, "min_reps": 5, "max_reps": 10},
    ])
    client.seed("exercise_relationships", [{
        "from_exercise_id": 100, "to_exercise_id": 101, "type": "regression", "reason": "Lack of strength",
    }])
    row = _seed_period_session(client, reps="10,10,10")  # 70% -> 7 < min 8

    _repo(client).start_session(5, is_period=True)

    assert (row["exercise_id"], row["reps"], row["rep_range"]) == (101, "5,5,5", "5-10")


def test_period_start_below_min_reps_without_regression_edge_clamps_to_min():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 8, "max_reps": 15}])
    row = _seed_period_session(client, reps="10,10,10")

    _repo(client).start_session(5, is_period=True)

    assert (row["exercise_id"], row["reps"], row["rep_range"]) == (100, "8,8,8", "8-12")


def test_restarting_a_started_period_session_does_not_scale_again():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 1, "max_reps": 15}])
    row = _seed_period_session(client, reps="7,7,7", started_at="2026-10-12T09:00:00+00:00")

    _repo(client).start_session(5, is_period=True)

    assert row["reps"] == "7,7,7"
    assert client.tables["sessions"][0]["is_period"] is False


def test_ordinary_start_leaves_reps_alone():
    client = FakeSupabaseClient()
    row = _seed_period_session(client, reps="10,10,10")

    _repo(client).start_session(5)

    assert row["reps"] == "10,10,10"
    assert client.tables["sessions"][0]["is_period"] is False


def test_progression_learns_from_the_last_non_period_session_not_the_period_one():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 1, "max_reps": 20}, {"id": 101, "min_reps": 1, "max_reps": 20}])
    repo = _repo(client)

    last_normal_week = [_row(id=1, reps="10,10,10", session_exercise_rpe={"rpe": 10},
                             session_exercise_set_logs=_hit("10,10,10"))]
    source = _after_streak(client, _source_plan(), last_normal_week)
    # The period week: swapped-in exercise at 70% reps, and a "too easy" RPE that must be ignored.
    period_week = [_row(id=2, exercise_id=101, reps="7,7,7", session_exercise_rpe={"rpe": 6},
                        session_exercise_set_logs=_hit("7,7,7"))]

    _progress(repo, "usr_1", source, period_week, period_days={1})

    [new_row] = client.inserted["session_exercises"]
    # Derived from the normal week's hard RPE (-1), not the period week's data.
    assert (new_row["exercise_id"], new_row["reps"]) == (100, "9,9,9")


def test_hold_check_uses_the_two_latest_non_period_sessions():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 1, "max_reps": 20}])
    # Chain: source plan 55 (period) <- 54 (period) <- 53 (normal) <- 52 (normal)
    client.seed("plans", [{"id": 54, "parent_plan_id": 53}, {"id": 53, "parent_plan_id": 52}])
    repo = _repo(client)

    plan_52 = [_row(id=1, reps="10,10,10", session_exercise_set_logs=_hit("10,10,10"))]
    plan_53 = [_row(id=2, reps="10,10,10", session_exercise_rpe={"rpe": 8},
                    session_exercise_set_logs=_hit("10,10,10"))]
    plan_54_period = [_row(id=3, reps="7,7,7", session_exercise_set_logs=_hit("7,7,7"))]
    _after_streak(client, _source_plan(), plan_52, parent_id=52)
    _after_streak(client, _source_plan(), plan_53, parent_id=53)
    _after_streak(client, _source_plan(), plan_54_period, parent_id=54, period_days={1})
    source = _source_plan(parent_plan_id=54)
    this_week = [_row(id=4, reps="7,7,7", session_exercise_set_logs=_hit("7,7,7"))]

    _progress(repo, "usr_1", source, this_week, period_days={1})

    [new_row] = client.inserted["session_exercises"]
    # Plans 53 and 52 both hit the same 10,10,10 targets, so the ramp advances.
    assert new_row["reps"] == "11,10,10"


@pytest.mark.parametrize("rpe, expected", [(8, "11,10,10"), (None, "11,10,10")])
def test_hold_check_skips_a_missed_week_like_a_period_week(rpe, expected):
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 1, "max_reps": 20}])
    # Chain: source plan 55 (done) <- 54 (missed) <- 53 (done)
    client.seed("plans", [{"id": 54, "parent_plan_id": 53}])
    repo = _repo(client)

    plan_53 = [_row(id=1, reps="10,10,10", session_exercise_set_logs=_hit("10,10,10"))]
    plan_54_missed = [_row(id=2, reps="10,10,10")]
    _after_streak(client, _source_plan(), plan_53, parent_id=53)
    _after_streak(client, _source_plan(), plan_54_missed, parent_id=54, missed_days={1})
    source = _source_plan(parent_plan_id=54)
    this_week = [_row(id=3, reps="10,10,10", session_exercise_rpe={"rpe": rpe} if rpe else None,
                      session_exercise_set_logs=_hit("10,10,10"))]

    _progress(repo, "usr_1", source, this_week)

    [new_row] = client.inserted["session_exercises"]
    # Plans 55 and 53 both hit 10,10,10; the missed week in between doesn't break the streak.
    assert new_row["reps"] == expected


def test_a_missed_week_with_nothing_before_it_is_still_no_streak():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 1, "max_reps": 20}])
    repo = _repo(client)

    source = _after_streak(client, _source_plan(), [_row(id=1, reps="10,10,10")], missed_days={1})
    this_week = [_row(id=2, reps="10,10,10", session_exercise_rpe={"rpe": 8},
                      session_exercise_set_logs=_hit("10,10,10"))]

    _progress(repo, "usr_1", source, this_week)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["reps"] == "10,10,10"


def test_day_with_no_non_period_history_carries_the_period_rows_forward():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 1, "max_reps": 20}])
    repo = _repo(client)

    period_week = [_row(reps="7,7,7", session_exercise_rpe={"rpe": 6}, session_exercise_set_logs=_hit("7,7,7"))]

    _progress(repo, "usr_1", _source_plan(), period_week, period_days={1})

    [new_row] = client.inserted["session_exercises"]
    assert new_row["reps"] == "7,7,7"


def test_progression_stops_looking_back_after_the_hop_limit(monkeypatch):
    monkeypatch.setattr(workout_plan_repository, "MAX_PROGRESSION_HOPS", 1)
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 1, "max_reps": 20}])
    client.seed("plans", [{"id": 54, "parent_plan_id": 53}])
    repo = _repo(client)

    # Plan 54 is a period week and plan 53 (a normal week) is beyond the limit.
    old_normal_week = [_row(id=1, reps="10,10,10", session_exercise_rpe={"rpe": 10})]
    _after_streak(client, _source_plan(), old_normal_week, parent_id=53)
    client.seed("sessions", [{
        "id": 454, "plan_id": 54, "day_number": 1, "scheduled_date": "2026-10-05",
        "completed_at": "2026-10-05T10:30:00+00:00", "is_period": True, "session_exercises": [],
    }])
    source = {**_source_plan(), "parent_plan_id": 54}
    period_week = [_row(id=3, reps="7,7,7", session_exercise_set_logs=_hit("7,7,7"))]

    _progress(repo, "usr_1", source, period_week, period_days={1})

    [new_row] = client.inserted["session_exercises"]
    assert new_row["reps"] == "7,7,7"


# --- timed (is_time_based) exercises ---------------------------------------------

def _timed_plank(client):
    client.seed("exercises", [{"id": 300, "min_reps": 10, "max_reps": 120, "is_time_based": True}])


@pytest.mark.parametrize("rpe, expected", [
    (8, "35,30,30"),   # correct: +5 s on the next set
    (6, "40,30,30"),   # too easy: +10 s
])
def test_timed_exercise_progresses_in_seconds_after_two_weeks_at_target(rpe, expected):
    client = FakeSupabaseClient()
    _timed_plank(client)
    repo = _repo(client)

    previous = [_row(id=1, exercise_id=300, reps="30,30,30", session_exercise_set_logs=_hit("30,30,30"))]
    source = _after_streak(client, _source_plan(), previous)
    this_week = [_row(id=2, exercise_id=300, reps="30,30,30", rep_range="10-120",
                      session_exercise_rpe={"rpe": rpe}, session_exercise_set_logs=_hit("30,30,30"))]

    _progress(repo, "usr_1", source, this_week)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["reps"] == expected


def test_timed_exercise_hard_drops_five_seconds_every_set():
    client = FakeSupabaseClient()
    _timed_plank(client)
    repo = _repo(client)

    rows = [_row(exercise_id=300, reps="30,35,30", session_exercise_rpe={"rpe": 10})]

    _progress(repo, "usr_1", _source_plan(), rows)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["reps"] == "25,30,25"


@pytest.mark.parametrize("rpe, expected", [
    (6, "40,30,30"),   # easy: +10 s straight away, no streak needed
    (8, "30,30,30"),   # correct: held until two weeks at target
])
def test_timed_exercise_without_a_two_week_streak(rpe, expected):
    client = FakeSupabaseClient()
    _timed_plank(client)
    repo = _repo(client)

    rows = [_row(exercise_id=300, reps="30,30,30", session_exercise_rpe={"rpe": rpe},
                 session_exercise_set_logs=_hit("30,30,30"))]

    _progress(repo, "usr_1", _source_plan(), rows)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["reps"] == expected


# --- admin monitor history --------------------------------------------------------

def _history_client():
    """usr_1 with a closed plan 6 (week of 5 Oct) and an open plan 7 (week of
    12 Oct), each 3_day: day 1 / 3 / 5."""
    client = FakeSupabaseClient()
    client.seed("plans", [
        {"id": 6, "user_id": "usr_1", "plan_type": "3_day", "completed": True},
        {"id": 7, "user_id": "usr_1", "plan_type": "3_day", "completed": False},
        {"id": 9, "user_id": "usr_other", "plan_type": "3_day", "completed": False},
    ])

    def session(id, plan_id, day, scheduled, completed_at=None, **extra):
        return {
            "id": id, "plan_id": plan_id, "day_number": day, "scheduled_date": scheduled,
            "started_at": None, "completed_at": completed_at,
            "session_exercises": [_row(id=id * 10, reps="10,10,10", exercises={"id": 100, "name": "Squat"},
                                       session_exercise_rpe=None)],
            **extra,
        }

    client.seed("sessions", [
        session(61, 6, 1, "2026-10-05", "2026-10-05T04:00:00+00:00",
                started_at="2026-10-05T03:30:00+00:00", is_period=True, feedback_audio_path="session_61.webm",
                session_analysis={"analysis": "Super!", "audio_url": "https://x/a.ogg"}),
        session(63, 6, 3, "2026-10-07"),                       # closed plan -> missed
        session(65, 6, 5, "2026-10-20"),                       # closed plan, future date -> still missed
        session(71, 7, 1, "2026-10-12", "2026-10-12T05:00:00+00:00"),
        session(73, 7, 3, "2026-10-14"),                       # date passed -> missed
        session(75, 7, 5, "2026-10-16"),                       # upcoming -> scheduled
        session(91, 9, 1, "2026-10-12"),                       # someone else's
    ])
    return client


def test_history_splits_scheduled_and_past_across_every_plan(monkeypatch):
    set_today(monkeypatch, date(2026, 10, 15))
    client = _history_client()

    history = _repo(client).get_user_workout_history("usr_1")

    assert [w["session_id"] for w in history["scheduled"]] == [75]
    assert [(w["session_id"], w["status"]) for w in history["past"]] == [
        (65, "missed"), (73, "missed"), (71, "completed"), (63, "missed"), (61, "completed"),
    ]


def test_history_carries_period_feedback_analysis_and_duration(monkeypatch):
    set_today(monkeypatch, date(2026, 10, 15))
    client = _history_client()

    past = _repo(client).get_user_workout_history("usr_1")["past"]
    first = next(w for w in past if w["session_id"] == 61)
    plain = next(w for w in past if w["session_id"] == 71)

    assert (first["is_period"], first["has_feedback"]) == (True, True)
    assert (first["analysis"], first["analysis_audio_url"]) == ("Super!", "https://x/a.ogg")
    assert first["duration_seconds"] == 1800
    assert first["exercises"][0]["rpe_logged"] is False
    assert (plain["is_period"], plain["has_feedback"], plain["analysis"], plain["duration_seconds"]) == (False, False, None, None)


def test_history_never_closes_or_progresses_a_plan(monkeypatch):
    set_today(monkeypatch, date(2026, 10, 30))  # every session of plan 7 is resolved by now
    client = _history_client()

    _repo(client).get_user_workout_history("usr_1")

    assert [p["completed"] for p in client.tables["plans"]] == [True, False, False]
    assert "plans" not in client.inserted


def test_history_for_a_client_with_no_plans_is_empty():
    assert _repo(FakeSupabaseClient()).get_user_workout_history("usr_new") == {"scheduled": [], "past": []}


# --- coach rebuilding the current week ---------------------------------------------

def _seed_week_to_regenerate(client, started_day=None, parent_plan_id=6):
    """Plan 7 (unfinished, 2026-10-12..16, see _seed_unfinished_plan) as the
    progression of plan 6, whose day 1/3/5 sessions all had 10,10,10 rated
    hard (rpe 10) with every set done — so progressing plan 6 again gives
    9,9,9."""
    _seed_unfinished_plan(client, {1: None, 3: None, 5: None})
    client.tables["plans"][0]["parent_plan_id"] = parent_plan_id
    if started_day is not None:
        next(s for s in client.tables["sessions"] if s["day_number"] == started_day)["started_at"] = (
            "2026-10-12T09:00:00+00:00"
        )
    client.seed("plans", [{
        "id": 6, "user_id": "usr_1", "plan_type": "3_day", "completed": True,
        "completed_at": "2026-10-11T18:00:00+00:00", "parent_plan_id": None,
        "plan_selection_reason": None, "medical_clearance_warning": None,
        "coach_notes": "keep it gentle", "safety_summary": None,
    }])
    client.seed("sessions", [
        {"id": 60 + day, "plan_id": 6, "day_number": day,
         "scheduled_date": date(2026, 10, 4 + day).isoformat(),
         "completed_at": "2026-10-05T10:30:00+00:00", "is_period": False,
         "session_exercises": [_row(id=600 + day, reps="10,10,10", session_exercise_rpe={"rpe": 10},
                                    session_exercise_set_logs=_hit("10,10,10"))]}
        for day in (1, 3, 5)
    ])


def test_regenerating_the_current_week_replaces_it_with_a_fresh_progression_on_the_same_dates(monkeypatch):
    client = FakeSupabaseClient()
    _seed_week_to_regenerate(client)
    set_today(monkeypatch, date(2026, 10, 12))
    repo = _repo(client)

    new_plan = repo.regenerate_current_plan("usr_1")

    assert "delete:plans" in client.query_log
    assert [p["id"] for p in client.tables["plans"]] == [6, new_plan["id"]]
    assert new_plan["parent_plan_id"] == 6
    assert new_plan["coach_notes"] == "keep it gentle"
    assert sorted((s["day_number"], s["scheduled_date"]) for s in client.inserted["sessions"]) == [
        (1, "2026-10-12"), (2, "2026-10-13"), (3, "2026-10-14"), (4, "2026-10-15"),
        (5, "2026-10-16"), (6, "2026-10-17"),
    ]
    assert [row["reps"] for row in client.inserted["session_exercises"]] == ["9,9,9"] * 3


@pytest.mark.parametrize("setup, message", [
    (dict(started_day=3), "already been started"),
    (dict(parent_plan_id=None), "first plan"),
])
def test_regenerating_is_refused_without_deleting_anything(monkeypatch, setup, message):
    client = FakeSupabaseClient()
    _seed_week_to_regenerate(client, **setup)
    set_today(monkeypatch, date(2026, 10, 12))
    repo = _repo(client)

    with pytest.raises(PlanRegenerationError, match=message):
        repo.regenerate_current_plan("usr_1")

    assert "delete:plans" not in client.query_log
    assert "plans" not in client.inserted


def test_regenerating_with_no_current_week_is_refused():
    with pytest.raises(PlanRegenerationError, match="no current week"):
        _repo(FakeSupabaseClient()).regenerate_current_plan("usr_1")


def test_coach_notes_are_read_from_and_written_to_the_unfinished_plan():
    client = FakeSupabaseClient()
    client.seed("plans", [
        {"id": 6, "user_id": "usr_1", "completed": True, "coach_notes": "old week"},
        {"id": 7, "user_id": "usr_1", "completed": False, "coach_notes": "this week"},
    ])
    repo = _repo(client)

    assert repo.get_current_plan_notes("usr_1") == client.tables["plans"][1]

    repo.update_coach_notes(7, "Keep the knees soft")

    assert [p["coach_notes"] for p in client.tables["plans"]] == ["old week", "Keep the knees soft"]


def test_prescription_edit_changes_the_note_only_when_given():
    client = FakeSupabaseClient()
    client.seed("session_exercises", [{"id": 70, "sets": 3, "reps": "10", "note": "keep form tight"}])
    repo = _repo(client)

    repo.update_session_exercise_prescription(70, 4, "12")
    assert client.tables["session_exercises"][0] == {"id": 70, "sets": 4, "reps": "12", "note": "keep form tight"}

    repo.update_session_exercise_prescription(70, 4, "12", note=None)
    assert client.tables["session_exercises"][0]["note"] is None


def test_prescription_edit_can_swap_the_exercise_and_its_rep_range():
    client = FakeSupabaseClient()
    client.seed("session_exercises", [
        {"id": 70, "exercise_id": 4, "sets": 3, "reps": "10", "rep_range": "8-12", "note": "keep form tight"},
    ])
    repo = _repo(client)

    repo.update_session_exercise_prescription(70, 2, "20", exercise={"id": 9, "min_reps": 20, "max_reps": 45})

    assert client.tables["session_exercises"][0] == {
        "id": 70, "exercise_id": 9, "sets": 2, "reps": "20", "rep_range": "20-45", "note": "keep form tight",
    }

    repo.update_session_exercise_prescription(70, 2, "20", exercise={"id": 5, "min_reps": None, "max_reps": 12})
    assert client.tables["session_exercises"][0]["rep_range"] is None


def test_completed_sessions_are_counted_across_every_plan_of_the_user():
    # 61 (plan 6) and 71 (plan 7) are completed; usr_other's session isn't counted.
    assert _repo(_history_client()).count_completed_sessions("usr_1") == 2


def test_a_client_with_no_plans_has_no_completed_sessions():
    assert _repo(FakeSupabaseClient()).count_completed_sessions("usr_new") == 0


# ---------- cardio days ----------

CIRCUIT = [
    {"id": 2, "name": "Side step", "video_path": "side-step.mp4", "poster_path": "side-step.jpg",
     "position": 2, "active": True},
    {"id": 1, "name": "Marching rows", "video_path": "marching-rows.mp4", "poster_path": "marching-rows.jpg",
     "position": 1, "active": True},
    {"id": 3, "name": "Retired", "video_path": "retired.mp4", "poster_path": None,
     "position": 3, "active": False},
]


def _cardio_session(day_number, rating=None, completed=True, level=(1, 30), plan_id=None, **extra):
    session = {
        "id": 600 + day_number + (plan_id or 0) * 10,
        "day_number": day_number,
        "scheduled_date": date(2026, 10, 11 + day_number).isoformat(),
        "completed_at": "2026-10-13T10:30:00+00:00" if completed else None,
        "is_period": False,
        "kind": "cardio",
        "cardio_rounds": level[0],
        "cardio_work_seconds": level[1],
        "cardio_rating": rating,
        "session_exercises": [],
        **extra,
    }
    if plan_id is not None:
        session["plan_id"] = plan_id
    return session


def _strength_session(day_number):
    return {
        "id": 500 + day_number,
        "day_number": day_number,
        "scheduled_date": date(2026, 10, 11 + day_number).isoformat(),
        "completed_at": "2026-10-12T10:30:00+00:00",
        "is_period": False,
        "kind": "strength",
        "session_exercises": [_row(id=day_number, session_exercise_rpe={"rpe": 8},
                                   session_exercise_set_logs=_hit("10,10,10"))],
    }


def _progress_cardio(client, cardio_sessions, source_plan=None):
    """Progress a 3_day week of three strength days plus cardio_sessions;
    returns the new plan's cardio session rows."""
    client.seed("exercises", [{"id": 100, "min_reps": 6, "max_reps": 15}])
    sessions = [_strength_session(d) for d in (1, 3, 5)] + cardio_sessions
    _repo(client).create_progressed_plan("usr_1", source_plan or _source_plan(), sessions)
    return [s for s in client.inserted["sessions"] if s["kind"] == "cardio"]


def _levels(rows):
    return {(r["day_number"], r["cardio_rounds"], r["cardio_work_seconds"]) for r in rows}


def test_create_plan_puts_cardio_on_days_3_and_6_of_a_4_day_plan_at_the_start_level():
    from agents.prompts_v1 import DAY_TEMPLATES

    client = FakeSupabaseClient()
    schedule = [
        {**day, "primary": [{"exercise_id": 100, "slot": "Squat", "sets": 3, "reps": "10"}], "secondary": []}
        if not day["is_rest_day"] else day
        for day in DAY_TEMPLATES["4_day"]["schedule"]
    ]

    _repo(client).create_plan("usr_1", {"plan_type": "4_day", "schedule": schedule}, date(2026, 10, 12))

    cardio = [s for s in client.inserted["sessions"] if s["kind"] == "cardio"]
    assert _levels(cardio) == {(3, 1, 30), (6, 1, 30)}
    assert [s["day_number"] for s in client.inserted["sessions"] if s["kind"] == "strength"] == [1, 2, 4, 5]
    # Day 7 stays a full rest day.
    assert 7 not in {s["day_number"] for s in client.inserted["sessions"]}


@pytest.mark.parametrize("ratings, expected", [
    (("easy", "easy", "hard"), (1, 40)),
    (("easy", "hard", None), (1, 20)),      # the 3rd wasn't done: 1-1 tie goes harder
    (("hard", "hard", "medium"), (1, 20)),
])
def test_progressed_plan_takes_the_weeks_majority_cardio_rating(ratings, expected):
    client = FakeSupabaseClient()
    sessions = [
        _cardio_session(day, rating=rating, completed=rating is not None)
        for day, rating in zip((2, 4, 6), ratings)
    ]

    cardio = _progress_cardio(client, sessions)

    assert _levels(cardio) == {(day, *expected) for day in (2, 4, 6)}


def test_a_week_with_every_cardio_session_missed_holds_the_level():
    client = FakeSupabaseClient()
    sessions = [_cardio_session(day, completed=False, level=(2, 40)) for day in (2, 4, 6)]

    assert _levels(_progress_cardio(client, sessions)) == {(d, 2, 40) for d in (2, 4, 6)}


def test_easy_at_60_seconds_adds_a_round_at_30():
    client = FakeSupabaseClient()
    sessions = [_cardio_session(day, rating="easy", level=(1, 60)) for day in (2, 4, 6)]

    assert _levels(_progress_cardio(client, sessions)) == {(d, 2, 30) for d in (2, 4, 6)}


def _seed_previous_cardio_week(client, plan_id, ratings, level, parent_plan_id=None, completed=True):
    client.seed("plans", [{"id": plan_id, "parent_plan_id": parent_plan_id}])
    client.seed("sessions", [
        _cardio_session(day, rating=rating, level=level, plan_id=plan_id, completed=completed)
        for day, rating in zip((2, 4, 6), ratings)
    ])


def test_a_medium_week_holds_the_first_time():
    client = FakeSupabaseClient()
    _seed_previous_cardio_week(client, 54, ("easy",) * 3, (1, 30))
    sessions = [_cardio_session(day, rating="medium", level=(1, 40)) for day in (2, 4, 6)]

    cardio = _progress_cardio(client, sessions, _source_plan(parent_plan_id=54))

    assert _levels(cardio) == {(d, 1, 40) for d in (2, 4, 6)}


def test_a_second_medium_week_at_the_same_level_steps_up():
    client = FakeSupabaseClient()
    _seed_previous_cardio_week(client, 54, ("medium",) * 3, (1, 40))
    sessions = [_cardio_session(day, rating="medium", level=(1, 40)) for day in (2, 4, 6)]

    cardio = _progress_cardio(client, sessions, _source_plan(parent_plan_id=54))

    assert _levels(cardio) == {(d, 1, 50) for d in (2, 4, 6)}


def test_the_medium_hold_skips_a_week_whose_cardio_was_all_missed():
    client = FakeSupabaseClient()
    _seed_previous_cardio_week(client, 53, ("medium",) * 3, (1, 40))
    _seed_previous_cardio_week(client, 54, (None,) * 3, (1, 40), parent_plan_id=53, completed=False)
    sessions = [_cardio_session(day, rating="medium", level=(1, 40)) for day in (2, 4, 6)]

    cardio = _progress_cardio(client, sessions, _source_plan(parent_plan_id=54))

    assert _levels(cardio) == {(d, 1, 50) for d in (2, 4, 6)}


def test_a_plan_from_before_cardio_gets_cardio_days_at_the_start_level():
    client = FakeSupabaseClient()

    cardio = _progress_cardio(client, [])

    assert _levels(cardio) == {(d, 1, 30) for d in (2, 4, 6)}
    # Strength progression is untouched: one row per strength day, none on cardio days.
    cardio_ids = {s["id"] for s in cardio}
    assert len(client.inserted["session_exercises"]) == 3
    assert not cardio_ids & {row["session_id"] for row in client.inserted["session_exercises"]}


def test_unfinished_plan_shows_cardio_days_with_their_circuit(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    client = FakeSupabaseClient()
    client.seed("plans", [{
        "id": 7, "user_id": "usr_1", "plan_type": "3_day", "completed": False, "completed_at": None,
        "plan_selection_reason": None, "medical_clearance_warning": None,
        "coach_notes": None, "safety_summary": None,
    }])
    client.seed("cardio_exercises", CIRCUIT)
    client.seed("sessions", [
        {**_cardio_session(2, completed=False, level=(1, 40), plan_id=7), "id": 22, "started_at": None},
    ])

    result = _repo(client).get_unfinished_plan("usr_1")

    day2 = result["plan"]["schedule"][1]
    assert (day2["split_name"], day2["is_rest_day"], day2["kind"], day2["session_id"]) == (
        "Cardio", False, "cardio", 22,
    )
    assert result["plan"]["schedule"][3]["is_rest_day"] is True   # day 4: no session, still rest
    assert result["plan"]["schedule"][3]["kind"] is None
    [workout] = result["workouts"]
    assert (workout["name"], workout["kind"]) == ("Cardio", "cardio")
    cardio = workout["cardio"]
    assert (cardio["rounds"], cardio["work_seconds"], cardio["rating"]) == (1, 40, None)
    assert cardio["exercise_rest_seconds"] == 13   # a third of 40 s
    assert cardio["estimated_seconds"] == 10 + 2 * 40 + 13
    assert [e["name"] for e in cardio["exercises"]] == ["Marching rows", "Side step"]
    assert cardio["exercises"][0]["video_url"] == (
        "https://proj.supabase.co/storage/v1/object/public/cardio-videos/marching-rows.mp4"
    )
    assert result["sessions"][2]["kind"] == "cardio"


def test_set_cardio_rating_only_rates_cardio_sessions():
    client = FakeSupabaseClient()
    client.seed("sessions", [
        {"id": 22, "kind": "cardio", "cardio_rating": None},
        {"id": 21, "kind": "strength"},
    ])
    repo = _repo(client)

    assert repo.set_cardio_rating(22, "hard")["cardio_rating"] == "hard"
    assert repo.set_cardio_rating(21, "hard") is None
    with pytest.raises(ValueError):
        repo.set_cardio_rating(22, "brutal")


def test_completing_a_cardio_session_reports_its_rounds_and_circuit():
    client = FakeSupabaseClient()
    plan_ref = {"user_id": "usr_1", "plan_type": "3_day", "completed": False}
    client.seed("plans", [{"id": 7, "user_id": "usr_1", "plan_type": "3_day", "completed": False}])
    client.seed("cardio_exercises", CIRCUIT)
    client.seed("sessions", [
        {**_cardio_session(2, rating="easy", completed=False, level=(2, 30), plan_id=7),
         "id": 22, "scheduled_date": "2026-10-12", "started_at": "2026-10-12T10:00:00+00:00",
         "plans": plan_ref},
        {"id": 23, "plan_id": 7, "day_number": 3, "scheduled_date": "2026-10-14", "completed_at": None,
         "kind": "strength"},
    ])

    summary = _repo(client).complete_session(22)

    assert summary["kind"] == "cardio"
    assert (summary["rounds"], summary["work_seconds"], summary["rating"]) == (2, 30, "easy")
    assert (summary["exercises_completed"], summary["total_exercises"]) == (2, 2)
    assert summary["plan_completed"] is False   # day 3 is still to come


def test_a_period_week_holds_the_cardio_level():
    client = FakeSupabaseClient()
    sessions = [_cardio_session(day, rating="easy", level=(1, 40), is_period=True) for day in (2, 4, 6)]

    assert _levels(_progress_cardio(client, sessions)) == {(d, 1, 40) for d in (2, 4, 6)}


def test_period_cardio_ratings_dont_vote():
    client = FakeSupabaseClient()
    sessions = [
        _cardio_session(2, rating="easy", is_period=True),
        _cardio_session(4, rating="easy", is_period=True),
        _cardio_session(6, rating="hard"),
    ]

    assert _levels(_progress_cardio(client, sessions)) == {(d, 1, 20) for d in (2, 4, 6)}


def test_the_medium_hold_skips_a_week_spent_on_her_period():
    client = FakeSupabaseClient()
    _seed_previous_cardio_week(client, 53, ("medium",) * 3, (1, 40))
    _seed_previous_cardio_week(client, 54, ("easy",) * 3, (1, 40), parent_plan_id=53)
    for session in client.tables["sessions"]:
        if session["plan_id"] == 54:
            session["is_period"] = True
    sessions = [_cardio_session(day, rating="medium", level=(1, 40)) for day in (2, 4, 6)]

    cardio = _progress_cardio(client, sessions, _source_plan(parent_plan_id=54))

    assert _levels(cardio) == {(d, 1, 50) for d in (2, 4, 6)}


def test_a_period_cardio_session_runs_at_70_percent_of_its_planned_seconds():
    client = FakeSupabaseClient()
    client.seed("plans", [{
        "id": 7, "user_id": "usr_1", "plan_type": "3_day", "completed": False, "completed_at": None,
        "plan_selection_reason": None, "medical_clearance_warning": None,
        "coach_notes": None, "safety_summary": None,
    }])
    client.seed("cardio_exercises", CIRCUIT)
    client.seed("sessions", [{
        **_cardio_session(2, completed=False, level=(1, 30), plan_id=7, is_period=True),
        "id": 22, "started_at": "2026-10-13T10:00:00+00:00",
    }])

    [workout] = _repo(client).get_unfinished_plan("usr_1")["workouts"]

    cardio = workout["cardio"]
    assert (cardio["work_seconds"], cardio["planned_work_seconds"], cardio["is_period"]) == (21, 30, True)
    assert cardio["exercise_rest_seconds"] == 7   # a third of the 21 s she does
    assert cardio["estimated_seconds"] == 10 + 2 * 21 + 7
    # The stored level is never touched.
    assert client.tables["sessions"][0]["cardio_work_seconds"] == 30


def test_completing_a_period_cardio_session_reports_the_seconds_she_did():
    client = FakeSupabaseClient()
    plan_ref = {"user_id": "usr_1", "plan_type": "3_day", "completed": False}
    client.seed("plans", [{"id": 7, "user_id": "usr_1", "plan_type": "3_day", "completed": False}])
    client.seed("cardio_exercises", CIRCUIT)
    client.seed("sessions", [
        {**_cardio_session(2, completed=False, level=(1, 50), plan_id=7, is_period=True),
         "id": 22, "scheduled_date": "2026-10-12", "started_at": "2026-10-12T10:00:00+00:00",
         "plans": plan_ref},
    ])

    summary = _repo(client).complete_session(22)

    assert (summary["work_seconds"], summary["is_period"]) == (35, True)


# ---------- cardio step log ----------

def _logging_session(**overrides):
    return {"id": 22, "kind": "cardio", "cardio_rounds": 2, "cardio_work_seconds": 30, "is_period": False,
            **overrides}


def _log_client():
    client = FakeSupabaseClient()
    client.seed("cardio_exercises", CIRCUIT)   # 2 active: Marching rows, Side step
    return client


def test_logging_an_exercise_fills_its_name_and_planned_seconds():
    client = _log_client()

    _repo(client).log_cardio_step(_logging_session(), 1, 1, "exercise", 12, 3, True)

    [row] = client.tables["session_cardio_logs"]
    assert (row["exercise_name"], row["cardio_exercise_id"], row["planned_seconds"]) == ("Side step", 2, 30)
    assert (row["actual_seconds"], row["paused_seconds"], row["skipped"]) == (12, 3, True)
    assert "rest_actual_seconds" not in row


def test_an_exercise_and_its_rest_land_on_one_row():
    client = _log_client()
    repo = _repo(client)

    repo.log_cardio_step(_logging_session(), 1, 0, "exercise", 30, 0, False)
    repo.log_cardio_step(_logging_session(), 1, 0, "rest", 4, 0, True)

    [row] = client.tables["session_cardio_logs"]
    assert (row["actual_seconds"], row["skipped"]) == (30, False)
    assert (row["rest_planned_seconds"], row["rest_actual_seconds"], row["rest_skipped"]) == (10, 4, True)


def test_the_rest_after_a_rounds_last_exercise_is_the_round_rest():
    client = _log_client()

    _repo(client).log_cardio_step(_logging_session(), 1, 1, "rest", 30, 5, False)

    [row] = client.tables["session_cardio_logs"]
    assert (row["rest_planned_seconds"], row["rest_paused_seconds"]) == (30, 5)
    # Still a valid row on its own: name and planned seconds are always sent.
    assert (row["exercise_name"], row["planned_seconds"]) == ("Side step", 30)


def test_a_period_session_logs_against_its_shorter_plan():
    client = _log_client()

    _repo(client).log_cardio_step(_logging_session(is_period=True), 1, 0, "rest", 7, 0, False)

    [row] = client.tables["session_cardio_logs"]
    assert (row["planned_seconds"], row["rest_planned_seconds"]) == (21, 7)


@pytest.mark.parametrize("session, args", [
    (_logging_session(kind="strength"), (1, 0, "exercise", 30, 0, False)),
    (_logging_session(), (3, 0, "exercise", 30, 0, False)),     # only 2 rounds
    (_logging_session(), (1, 2, "exercise", 30, 0, False)),     # only 2 exercises
    (_logging_session(), (1, 0, "warmup", 30, 0, False)),
    (_logging_session(), (1, 0, "exercise", 601, 0, False)),
    (_logging_session(), (1, 0, "exercise", 30, -1, False)),
    (_logging_session(), (2, 1, "rest", 10, 0, False)),         # nothing after the last one
])
def test_logging_a_step_that_doesnt_exist_is_refused(session, args):
    from backend.repository.workout_plan_repository import CardioLogError

    client = _log_client()
    with pytest.raises(CardioLogError):
        _repo(client).log_cardio_step(session, *args)
    assert not client.tables.get("session_cardio_logs")


def test_the_cardio_block_carries_the_log_and_its_summary(monkeypatch):
    client = FakeSupabaseClient()
    client.seed("plans", [{
        "id": 7, "user_id": "usr_1", "plan_type": "3_day", "completed": False, "completed_at": None,
        "plan_selection_reason": None, "medical_clearance_warning": None,
        "coach_notes": None, "safety_summary": None,
    }])
    client.seed("cardio_exercises", CIRCUIT)

    def log_row(round_number, position, actual, skipped=False, paused=0, rest=None, rest_skipped=False):
        return {"round": round_number, "position": position, "exercise_name": CIRCUIT[1 - position]["name"],
                "planned_seconds": 30, "actual_seconds": actual, "paused_seconds": paused, "skipped": skipped,
                "rest_planned_seconds": 10 if rest is not None else None, "rest_actual_seconds": rest,
                "rest_paused_seconds": 0 if rest is not None else None, "rest_skipped": rest_skipped}

    client.seed("sessions", [{
        **_cardio_session(2, completed=True, level=(2, 30), plan_id=7), "id": 22,
        "started_at": "2026-10-13T10:00:00+00:00", "scheduled_date": "2026-10-13",
        # Out of order on purpose; round 2's second exercise was never reached.
        "session_cardio_logs": [
            log_row(2, 0, 30),
            log_row(1, 1, 12, skipped=True, paused=40, rest=30),
            log_row(1, 0, 30, rest=3, rest_skipped=True),
        ],
    }])

    [workout] = _repo(client).get_unfinished_plan("usr_1", close_if_resolved=False)["workouts"]

    cardio = workout["cardio"]
    assert [(e["round"], e["position"]) for e in cardio["log"]] == [(1, 0), (1, 1), (2, 0)]
    assert cardio["log_summary"] == {
        "exercises_done": 2,
        "exercises_skipped": 1,
        "exercises_missing": 1,
        "rests_skipped": 1,
        "active_seconds": 72,
        "paused_seconds": 40,
    }


# ---------- exercises skipped by the coach (AI Coach suggestions) ----------

from unittest.mock import MagicMock  # noqa: E402

from backend.repository.workout_plan_repository import (  # noqa: E402
    WorkoutPlanRepository,
    _flatten_session_exercises,
)


def _skip_row(row_id, skipped):
    return {
        "id": row_id, "category": "primary", "slot_label": "Squat", "sets": 3, "reps": "10",
        "skipped": skipped, "skip_reason": "Knee pain" if skipped else None,
        "exercises": {"id": row_id, "name": f"Ex {row_id}", "movement_types": {"name": "squat"}},
        "session_exercise_set_logs": [], "session_exercise_rpe": None,
    }


def test_a_skipped_exercise_carries_forward_like_a_missed_one():
    sessions = [{"day_number": 1, "completed_at": "2026-11-09T00:00:00+00:00",
                 "session_exercises": [_skip_row(1, False), _skip_row(2, True)]}]

    rows = _flatten_session_exercises(sessions)

    assert [(row["id"], row["missed"]) for row in rows] == [(1, False), (2, True)]


def test_a_skipped_exercise_is_left_out_of_her_workout_run_but_shown_in_entries():
    plan = {"id": 1, "plan_type": "3_day", "plan_selection_reason": None, "medical_clearance_warning": None,
            "coach_notes": None, "safety_summary": None}
    session = {"id": 88, "day_number": 1, "scheduled_date": "2026-11-16", "kind": "strength",
               "session_exercises": [_skip_row(1, False), _skip_row(2, True)]}
    repo = MagicMock()

    schedule = WorkoutPlanRepository._reconstruct_plan(repo, plan, [session])["schedule"]
    entries = WorkoutPlanRepository._workout_entries(repo, plan, [session])

    day_one = next(day for day in schedule if day["day_number"] == 1)
    assert [ex["id"] for ex in day_one["primary"]] == [1]
    assert [(ex["id"], ex["skipped"], ex["skip_reason"]) for ex in entries[0]["exercises"]] == [
        (1, False, None), (2, True, "Knee pain"),
    ]
