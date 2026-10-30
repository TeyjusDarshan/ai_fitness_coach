"""Tests for the coach client-monitor endpoints in
backend/controllers/admin_monitor_controller.py. The repository methods they
call are swapped for MagicMocks (Supabase is mocked by conftest.app_module).
"""
from unittest.mock import MagicMock

import pytest

ADMIN_KEY = "test-admin-key"
ADMIN_HEADERS = {"X-Admin-Key": ADMIN_KEY}


@pytest.fixture
def monitor(app_module, monkeypatch):
    import backend.controllers.admin_monitor_controller as controller

    monkeypatch.setenv("ADMIN_API_KEY", ADMIN_KEY)
    repo = controller.plan_repo
    monkeypatch.setattr(repo, "list_user_profiles", MagicMock(return_value=[
        {"user_id": "usr_1", "name": "Asha", "gender": "female", "updated_at": "2026-10-01T00:00:00+00:00"},
        {"user_id": "usr_2", "name": "Ravi", "gender": "male", "updated_at": "2026-10-02T00:00:00+00:00"},
    ]))
    monkeypatch.setattr(repo, "get_user_profile_row", MagicMock(return_value={
        "user_id": "usr_1", "name": "Asha", "gender": "female",
        "profile": {"demographics": {"age": 52, "sex": "female"}, "goals": {"primary_goal": "strength"},
                    "experience": {"training_experience_level": "beginner"}, "availability": {"days_per_week": 3}},
    }))
    monkeypatch.setattr(repo, "list_joint_pain", MagicMock(return_value=[{"joint": "knee", "pain_level": "mild"}]))
    monkeypatch.setattr(repo, "list_period_days", MagicMock(return_value=["2026-10-12"]))
    monkeypatch.setattr(repo, "get_user_workout_history", MagicMock(return_value={"scheduled": [], "past": [{"session_id": 5}]}))
    monkeypatch.setattr(repo, "get_current_plan_notes", MagicMock(return_value={"id": 7, "coach_notes": "Go slow"}))
    monkeypatch.setattr(controller.auth_repo, "passkey_summary", MagicMock(
        side_effect=lambda user_id=None: {"usr_1": {"passkeys": 1, "last_used_at": "2026-10-12T05:00:00+00:00"}}
    ))
    return app_module.app.test_client(), controller


@pytest.mark.parametrize("path", ["/api/admin/users", "/api/admin/users/usr_1/monitor"])
def test_monitor_endpoints_require_the_admin_key(monitor, path):
    client, _ = monitor
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"X-Admin-Key": "wrong"}).status_code == 401


def test_client_list_flags_who_has_a_passkey(monitor):
    client, _ = monitor

    response = client.get("/api/admin/users", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    assert [(c["user_id"], c["name"], c["has_passkey"]) for c in response.get_json()] == [
        ("usr_1", "Asha", True), ("usr_2", "Ravi", False),
    ]


def test_monitor_returns_client_details_and_workouts(monitor):
    client, controller = monitor

    response = client.get("/api/admin/users/usr_1/monitor", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    body = response.get_json()
    assert body["client"] == {
        "user_id": "usr_1", "name": "Asha", "gender": "female",
        "profile": {"age": 52, "sex": "female", "primary_goal": "strength", "experience_level": "beginner", "days_per_week": 3},
        "joint_pain": [{"joint": "knee", "pain_level": "mild"}],
        "period_days": ["2026-10-12"],
        "sign_in": {"passkeys": 1, "last_used_at": "2026-10-12T05:00:00+00:00"},
    }
    assert body["workouts"] == {"scheduled": [], "past": [{"session_id": 5}]}
    controller.plan_repo.get_user_workout_history.assert_called_once_with("usr_1")


def test_monitor_for_a_client_without_a_passkey_says_so(monitor):
    client, controller = monitor
    controller.auth_repo.passkey_summary.side_effect = lambda user_id=None: {}

    body = client.get("/api/admin/users/usr_1/monitor", headers=ADMIN_HEADERS).get_json()

    assert body["client"]["sign_in"] == {"passkeys": 0, "last_used_at": None}


def test_monitor_for_an_unknown_client_is_404(monitor):
    client, controller = monitor
    controller.plan_repo.get_user_profile_row.return_value = None

    assert client.get("/api/admin/users/nobody/monitor", headers=ADMIN_HEADERS).status_code == 404
    controller.plan_repo.get_user_workout_history.assert_not_called()


# --- editing an upcoming workout's prescription ---------------------------------

def _slot(completed_at=None, scheduled_date="2026-10-20", plan_completed=False, logs=()):
    return {
        "id": 70, "sets": 3, "reps": "10",
        "session_exercise_set_logs": [{"set_number": n} for n in logs],
        "sessions": {"id": 7, "scheduled_date": scheduled_date, "completed_at": completed_at,
                     "plans": {"user_id": "usr_1", "completed": plan_completed}},
    }


@pytest.fixture
def editing(monitor, monkeypatch):
    client, controller = monitor
    monkeypatch.setattr(controller, "app_today", lambda: __import__("datetime").date(2026, 10, 15))
    monkeypatch.setattr(controller.plan_repo, "get_session_exercise_for_edit", MagicMock(return_value=_slot()))
    monkeypatch.setattr(controller.plan_repo, "update_session_exercise_prescription", MagicMock())
    return client, controller


def _edit(client, body, headers=ADMIN_HEADERS):
    return client.patch("/api/admin/session-exercises/70", json=body, headers=headers)


@pytest.mark.parametrize("reps, stored", [([12, 12, 12, 12], "12"), ([12, 12, 11, 10], "12,12,11,10")])
def test_editing_an_upcoming_exercise_stores_sets_and_targets(editing, reps, stored):
    client, controller = editing

    response = _edit(client, {"sets": 4, "reps": reps})

    assert response.status_code == 200
    assert response.get_json() == {"id": 70, "sets": 4, "reps": stored}
    controller.plan_repo.update_session_exercise_prescription.assert_called_once_with(70, 4, stored)


@pytest.mark.parametrize("sent, stored", [
    ("  Squeeze at the top  ", "Squeeze at the top"),
    ("", None),
    (None, None),
])
def test_editing_can_change_the_exercise_note(editing, sent, stored):
    client, controller = editing

    response = _edit(client, {"sets": 3, "reps": [10, 10, 10], "note": sent})

    assert response.status_code == 200
    assert response.get_json() == {"id": 70, "sets": 3, "reps": "10", "note": stored}
    controller.plan_repo.update_session_exercise_prescription.assert_called_once_with(70, 3, "10", note=stored)


@pytest.mark.parametrize("note", [5, "x" * 501])
def test_editing_rejects_a_bad_note(editing, note):
    client, controller = editing
    assert _edit(client, {"sets": 1, "reps": [10], "note": note}).status_code == 400
    controller.plan_repo.update_session_exercise_prescription.assert_not_called()


def test_editing_needs_the_admin_key(editing):
    client, controller = editing
    assert _edit(client, {"sets": 3, "reps": [10, 10, 10]}, headers={}).status_code == 401
    controller.plan_repo.update_session_exercise_prescription.assert_not_called()


@pytest.mark.parametrize("body", [
    {"sets": 0, "reps": []},
    {"sets": 11, "reps": [10] * 11},
    {"sets": 3, "reps": [10, 10]},          # one target per set
    {"sets": 2, "reps": [10, 0]},
    {"sets": 2, "reps": [10, "10"]},
    {"sets": True, "reps": [10]},
    {"sets": 1, "reps": [601]},
])
def test_editing_rejects_bad_values(editing, body):
    client, controller = editing
    assert _edit(client, body).status_code == 400
    controller.plan_repo.update_session_exercise_prescription.assert_not_called()


@pytest.mark.parametrize("slot", [
    _slot(completed_at="2026-10-14T05:00:00+00:00"),   # done
    _slot(scheduled_date="2026-10-13"),                # date passed -> missed
    _slot(plan_completed=True),                        # plan closed -> missed
    _slot(logs=(1,)),                                  # in progress
])
def test_only_untouched_upcoming_workouts_can_be_edited(editing, slot):
    client, controller = editing
    controller.plan_repo.get_session_exercise_for_edit.return_value = slot

    assert _edit(client, {"sets": 3, "reps": [10, 10, 10]}).status_code == 409
    controller.plan_repo.update_session_exercise_prescription.assert_not_called()


def test_editing_an_unknown_slot_is_404(editing):
    client, controller = editing
    controller.plan_repo.get_session_exercise_for_edit.return_value = None
    assert _edit(client, {"sets": 3, "reps": [10, 10, 10]}).status_code == 404


def test_regenerate_plan_requires_the_admin_key(monitor):
    client, _ = monitor
    assert client.post("/api/admin/users/usr_1/regenerate-plan").status_code == 401


def test_regenerate_plan_rebuilds_the_current_week(monitor, monkeypatch):
    client, controller = monitor
    monkeypatch.setattr(controller.plan_repo, "user_exists", MagicMock(return_value=True))
    regenerate = MagicMock(return_value={"id": 42})
    monkeypatch.setattr(controller.plan_repo, "regenerate_current_plan", regenerate)

    response = client.post("/api/admin/users/usr_1/regenerate-plan", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    assert response.get_json() == {"plan_id": 42}
    regenerate.assert_called_once_with("usr_1")


def test_regenerate_plan_refusal_is_a_409_with_the_reason(monitor, monkeypatch):
    from backend.repository.workout_plan_repository import PlanRegenerationError

    client, controller = monitor
    monkeypatch.setattr(controller.plan_repo, "user_exists", MagicMock(return_value=True))
    monkeypatch.setattr(controller.plan_repo, "regenerate_current_plan", MagicMock(
        side_effect=PlanRegenerationError("A workout in this week has already been started, so it can't be rebuilt.")
    ))

    response = client.post("/api/admin/users/usr_1/regenerate-plan", headers=ADMIN_HEADERS)

    assert response.status_code == 409
    assert "already been started" in response.get_json()["error"]


def test_regenerate_plan_for_an_unknown_client_is_a_404(monitor, monkeypatch):
    client, controller = monitor
    monkeypatch.setattr(controller.plan_repo, "user_exists", MagicMock(return_value=False))

    response = client.post("/api/admin/users/nobody/regenerate-plan", headers=ADMIN_HEADERS)

    assert response.status_code == 404


def test_monitor_includes_the_current_weeks_coach_notes(monitor):
    client, _ = monitor

    response = client.get("/api/admin/users/usr_1/monitor", headers=ADMIN_HEADERS)

    assert response.get_json()["current_plan"] == {"id": 7, "coach_notes": "Go slow"}


@pytest.mark.parametrize("sent, stored", [
    ("  Keep the knees soft  ", "Keep the knees soft"),
    ("   ", None),
    (None, None),
])
def test_coach_notes_are_saved_on_the_current_week(monitor, monkeypatch, sent, stored):
    client, controller = monitor
    monkeypatch.setattr(controller.plan_repo, "user_exists", MagicMock(return_value=True))
    update = MagicMock()
    monkeypatch.setattr(controller.plan_repo, "update_coach_notes", update)

    response = client.patch(
        "/api/admin/users/usr_1/coach-notes", json={"coach_notes": sent}, headers=ADMIN_HEADERS
    )

    assert response.status_code == 200
    assert response.get_json() == {"id": 7, "coach_notes": stored}
    update.assert_called_once_with(7, stored)


@pytest.mark.parametrize("body", [{"coach_notes": 5}, {"coach_notes": "x" * 2001}])
def test_invalid_coach_notes_are_rejected(monitor, body):
    client, _ = monitor

    response = client.patch("/api/admin/users/usr_1/coach-notes", json=body, headers=ADMIN_HEADERS)

    assert response.status_code == 400


def test_coach_notes_without_a_current_week_is_a_409(monitor, monkeypatch):
    client, controller = monitor
    monkeypatch.setattr(controller.plan_repo, "user_exists", MagicMock(return_value=True))
    monkeypatch.setattr(controller.plan_repo, "get_current_plan_notes", MagicMock(return_value=None))

    response = client.patch(
        "/api/admin/users/usr_1/coach-notes", json={"coach_notes": "hi"}, headers=ADMIN_HEADERS
    )

    assert response.status_code == 409


def test_coach_notes_require_the_admin_key(monitor):
    client, _ = monitor
    assert client.patch("/api/admin/users/usr_1/coach-notes", json={"coach_notes": "hi"}).status_code == 401
