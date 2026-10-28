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
from backend.repository.workout_plan_repository import PainLevel, WorkoutPlanRepository, is_session_missed
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

    def select(self, *_args, **_kwargs):
        return self

    def update(self, values):
        self._update = values
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


def _progress(repo, user_id, source_plan, exercise_rows, missed_days=()):
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
            "session_exercises": [],
        })
        session["session_exercises"].append({k: v for k, v in row.items() if k != "day_number"})
    return repo.create_progressed_plan(user_id, source_plan, list(sessions.values()))


def _hit(reps):
    """Set logs completing every set at exactly its target reps."""
    return [{"set_number": i, "completed_reps": int(r)} for i, r in enumerate(reps.split(","), start=1)]


def _after_streak(client, source_plan, previous_rows, parent_id=54, missed_days=()):
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


def test_first_week_at_a_target_is_copied_forward_even_when_rpe_says_progress():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 100, "min_reps": 6, "max_reps": 20}])
    repo = _repo(client)

    this_week = [_row(reps="10,9,9", session_exercise_rpe={"rpe": 6}, session_exercise_set_logs=_hit("10,9,9"))]

    _progress(repo, "usr_1", _source_plan(), this_week)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["reps"] == "10,9,9"


@pytest.mark.parametrize("previous_reps, previous_logs, this_logs, previous_missed", [
    ("10,9,9", "10,9,8", "10,9,9", False),    # last week fell short of target
    ("10,9,9", "10,9,9", "10,9,8", False),    # this week fell short of target
    ("10,9,9", "10,9,9", "10,9", False),      # a set was never logged
    ("9,9,9", "9,9,9", "10,9,9", False),      # targets changed since last week: streak restarts
    ("10,9,9", "10,9,9", "10,9,9", True),     # last week's session was missed
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
    )]

    plan = _progress(repo, "usr_2", _source_plan(), exercise_rows)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["exercise_id"] == 201
    assert new_row["reps"] == "4,4,4"
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

    previous = [_row(id=1, exercise_id=400, reps="20,19,19", session_exercise_set_logs=_hit("20,19,19"))]
    source = _after_streak(client, _source_plan(), previous)
    exercise_rows = [_row(
        id=4, exercise_id=400, reps="20,19,19", session_exercise_rpe={"rpe": 6},
        session_exercise_set_logs=_hit("20,19,19"),
    )]

    plan = _progress(repo, "usr_4", source, exercise_rows)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["exercise_id"] == 401
    assert new_row["reps"] == "10,10,10"
    assert new_row["rep_range"] == "10-18"
    assert new_row["session_id"] == client.inserted["sessions"][0]["id"]


def test_above_max_without_progression_edge_clamps_every_set_to_own_max_reps():
    client = FakeSupabaseClient()
    client.seed("exercises", [{"id": 500, "min_reps": 8, "max_reps": 20}])
    repo = _repo(client)

    previous = [_row(id=1, exercise_id=500, reps="20,19,19", session_exercise_set_logs=_hit("20,19,19"))]
    source = _after_streak(client, _source_plan(), previous)
    exercise_rows = [_row(
        id=5, exercise_id=500, reps="20,19,19", session_exercise_rpe={"rpe": 6},
        session_exercise_set_logs=_hit("20,19,19"),
    )]

    _progress(repo, "usr_5", source, exercise_rows)

    [new_row] = client.inserted["session_exercises"]
    assert new_row["exercise_id"] == 500
    assert new_row["reps"] == "20,20,20"
    assert new_row["rep_range"] == "8-12"


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
    assert [(s["plan_id"], s["day_number"], s["scheduled_date"]) for s in sessions] == [
        (plan["id"], 1, "2026-10-13"),
        (plan["id"], 3, "2026-10-15"),
        (plan["id"], 5, "2026-10-17"),
    ]
    session_ids = [s["id"] for s in sessions]
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
        _row(id=2, day_number=3, reps="10,10,10", session_exercise_rpe={"rpe": 8}),
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
    assert sessions == {1: "2026-10-30", 3: "2026-11-01"}


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
