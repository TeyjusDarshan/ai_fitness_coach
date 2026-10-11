"""Route guards on backend/app.py: signed-in users may only reach their own
dashboard/sessions, and coach routes require the X-Admin-Key header."""
from unittest.mock import MagicMock

import pytest

ADMIN_KEY = "test-admin-key"


@pytest.fixture(autouse=True)
def admin_key(monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", ADMIN_KEY)


def test_dashboard_without_session_is_401(app_module):
    assert app_module.app.test_client().get("/api/users/usr_1/dashboard").status_code == 401


def test_dashboard_for_another_user_is_403(app_module, sign_in, monkeypatch):
    monkeypatch.setattr(app_module.plan_repo, "get_unfinished_session", MagicMock())

    response = sign_in("usr_1").get("/api/users/usr_2/dashboard")

    assert response.status_code == 403
    app_module.plan_repo.get_unfinished_session.assert_not_called()


@pytest.mark.parametrize("method, path, body", [
    ("post", "/api/sessions/42/days/1/start", None),
    ("patch", "/api/sessions/42/exercises/7/sets/1", {"completed_reps": 10}),
    ("patch", "/api/sessions/42/exercises/7/rpe", {"rpe": 8}),
    ("post", "/api/sessions/42/days/1/complete", None),
])
def test_session_routes_reject_other_users_session(app_module, sign_in, monkeypatch, method, path, body):
    monkeypatch.setattr(app_module.plan_repo, "get_session_owner", MagicMock(return_value="usr_2"))
    for repo_method in ("start_day", "log_set", "log_rpe", "complete_day"):
        monkeypatch.setattr(app_module.plan_repo, repo_method, MagicMock())
    client = sign_in("usr_1")

    response = getattr(client, method)(path, json=body)

    assert response.status_code == 403
    for repo_method in ("start_day", "log_set", "log_rpe", "complete_day"):
        getattr(app_module.plan_repo, repo_method).assert_not_called()


def test_session_routes_without_session_are_401(app_module):
    client = app_module.app.test_client()
    assert client.post("/api/sessions/42/days/1/start").status_code == 401


@pytest.mark.parametrize("headers", [{}, {"X-Admin-Key": "wrong"}])
def test_coach_routes_require_admin_key(app_module, monkeypatch, headers):
    monkeypatch.setattr(app_module.plan_repo, "delete_joint_pain", MagicMock())

    response = app_module.app.test_client().delete("/api/users/usr_1/joint-pain/3", headers=headers)

    assert response.status_code == 401
    app_module.plan_repo.delete_joint_pain.assert_not_called()


def test_coach_routes_pass_with_admin_key(app_module, monkeypatch):
    monkeypatch.setattr(app_module.plan_repo, "user_exists", MagicMock(return_value=True))
    monkeypatch.setattr(app_module.plan_repo, "delete_joint_pain", MagicMock(return_value=True))

    response = app_module.app.test_client().delete(
        "/api/users/usr_1/joint-pain/3", headers={"X-Admin-Key": ADMIN_KEY}
    )

    assert response.status_code == 200
    app_module.plan_repo.delete_joint_pain.assert_called_once_with("usr_1", 3)
