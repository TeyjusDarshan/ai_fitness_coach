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
