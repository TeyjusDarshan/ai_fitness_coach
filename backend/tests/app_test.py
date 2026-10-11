"""Tests for the PWA's session endpoints (POST /api/sessions/<session_id>/start
and /complete, plus the scheduled-date lock shared with set/RPE logging) and
the dashboard.

Supabase is mocked (see conftest.app_module): the plan_repo methods these
endpoints call are swapped for MagicMocks so these tests exercise only the
endpoints' own logic, not the repository's Supabase queries.
"""
from datetime import date
from unittest.mock import MagicMock

import pytest

TODAY = date(2026, 10, 13)


@pytest.fixture(autouse=True)
def fixed_today(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "app_today", lambda: TODAY)


def _summary(plan_completed=False):
    return {
        "session_id": 42,
        "day_number": 2,
        "exercises_completed": 3,
        "total_exercises": 3,
        "sets_completed": 9,
        "total_sets": 9,
        "total_time_seconds": 1800,
        "plan_completed": plan_completed,
    }


def _session_42(app_module, monkeypatch, owner="usr_1", scheduled_date="2026-10-13"):
    monkeypatch.setattr(app_module.plan_repo, "get_session", MagicMock(return_value={
        "id": 42,
        "plan_id": 7,
        "day_number": 2,
        "scheduled_date": scheduled_date,
        "plans": {"user_id": owner, "plan_type": "3_day", "completed": False},
    }))


# --- complete ------------------------------------------------------------------

def test_complete_session_success_returns_summary(app_module, sign_in, monkeypatch):
    _session_42(app_module, monkeypatch)
    summary = _summary()
    monkeypatch.setattr(app_module.plan_repo, "complete_session", MagicMock(return_value=summary))

    response = sign_in("usr_1").post("/api/sessions/42/complete")

    assert response.status_code == 200
    assert response.get_json() == summary
    app_module.plan_repo.complete_session.assert_called_once_with(42)


def test_complete_session_not_found_returns_404(app_module, sign_in, monkeypatch):
    monkeypatch.setattr(app_module.plan_repo, "get_session", MagicMock(return_value=None))
    monkeypatch.setattr(app_module.plan_repo, "complete_session", MagicMock())

    response = sign_in("usr_1").post("/api/sessions/999/complete")

    assert response.status_code == 404
    app_module.plan_repo.complete_session.assert_not_called()


def test_complete_session_repo_failure_returns_500(app_module, sign_in, monkeypatch):
    _session_42(app_module, monkeypatch)
    monkeypatch.setattr(
        app_module.plan_repo, "complete_session", MagicMock(side_effect=RuntimeError("db unreachable"))
    )

    response = sign_in("usr_1").post("/api/sessions/42/complete")

    assert response.status_code == 500


# --- start + scheduled-date lock -------------------------------------------------

def test_start_session_on_its_date_starts_it(app_module, sign_in, monkeypatch):
    _session_42(app_module, monkeypatch, scheduled_date="2026-10-13")
    monkeypatch.setattr(app_module.plan_repo, "start_session", MagicMock(return_value={"id": 42}))

    response = sign_in("usr_1").post("/api/sessions/42/start")

    assert response.status_code == 200
    app_module.plan_repo.start_session.assert_called_once_with(42)


def test_start_session_after_its_date_is_still_allowed(app_module, sign_in, monkeypatch):
    _session_42(app_module, monkeypatch, scheduled_date="2026-10-11")
    monkeypatch.setattr(app_module.plan_repo, "start_session", MagicMock(return_value={"id": 42}))

    assert sign_in("usr_1").post("/api/sessions/42/start").status_code == 200


@pytest.mark.parametrize("method, path, body, repo_method", [
    ("post", "/api/sessions/42/start", None, "start_session"),
    ("patch", "/api/sessions/42/exercises/7/sets/1", {"completed_reps": 10}, "log_set"),
    ("patch", "/api/sessions/42/exercises/7/rpe", {"rpe": 8}, "log_rpe"),
    ("post", "/api/sessions/42/complete", None, "complete_session"),
])
def test_session_before_its_date_is_locked(app_module, sign_in, monkeypatch, method, path, body, repo_method):
    _session_42(app_module, monkeypatch, scheduled_date="2026-10-14")
    monkeypatch.setattr(app_module.plan_repo, repo_method, MagicMock())

    response = getattr(sign_in("usr_1"), method)(path, json=body)

    assert response.status_code == 409
    assert response.get_json() == {
        "error": "This workout opens on Wed 14 Oct.",
        "scheduled_date": "2026-10-14",
    }
    getattr(app_module.plan_repo, repo_method).assert_not_called()


# --- dashboard -------------------------------------------------------------------

def _schedule_day(day_number, is_rest_day, session_id=None, scheduled_date=None):
    return {
        "day_number": day_number,
        "day_label": f"Day {day_number}",
        "split_name": "Rest" if is_rest_day else "Full Body",
        "is_rest_day": is_rest_day,
        "session_id": session_id,
        "scheduled_date": scheduled_date,
        "primary": [],
        "secondary": [],
    }


def test_dashboard_dates_and_locks_each_day(app_module, sign_in, monkeypatch):
    sessions = {
        1: {"id": 11, "scheduled_date": "2026-10-12", "started_at": "x", "completed_at": "y"},
        3: {"id": 13, "scheduled_date": "2026-10-14", "started_at": None, "completed_at": None},
    }
    plan = {
        "plan_type": "3_day",
        "plan_selection_reason": None,
        "medical_clearance_warning": None,
        "coach_notes": None,
        "safety_summary": None,
        "schedule": [
            _schedule_day(1, False, 11, "2026-10-12"),
            _schedule_day(2, True),
            _schedule_day(3, False, 13, "2026-10-14"),
        ],
    }
    monkeypatch.setattr(
        app_module.plan_repo,
        "get_unfinished_plan",
        MagicMock(return_value={"id": 7, "completed": False, "plan": plan, "sessions": sessions}),
    )
    monkeypatch.setattr(app_module.plan_repo, "get_profile", MagicMock(return_value={}))

    response = sign_in("usr_1").get("/api/users/usr_1/dashboard")

    assert response.status_code == 200
    data = response.get_json()
    assert data["plan_id"] == 7
    days = [(d["day_number"], d["session_id"], d["date"], d["status"], d["locked"]) for d in data["days"]]
    assert days == [
        (1, 11, "2026-10-12", "completed", False),
        (2, None, "2026-10-13", "rest", False),
        (3, 13, "2026-10-14", "next", True),
    ]
