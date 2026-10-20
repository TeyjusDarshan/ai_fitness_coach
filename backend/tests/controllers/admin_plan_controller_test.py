"""Tests for the coach plan-builder endpoints in
backend/controllers/admin_plan_controller.py.

Supabase is mocked (see conftest.app_module); the repository methods and the
preprocessor agent the endpoints call are swapped for MagicMocks.
"""
from datetime import date
from unittest.mock import MagicMock

import pytest

from agents.prompts_v1 import DAY_TEMPLATES

ADMIN_KEY = "test-admin-key"
ADMIN_HEADERS = {"X-Admin-Key": ADMIN_KEY}

EXERCISES = [
    {"id": 1, "name": "Glute Bridge", "min_reps": 8, "max_reps": 15},
    {"id": 2, "name": "Band Row", "min_reps": None, "max_reps": None},
]
PROFILE = {"user_id": "usr_new", "health": {"medical_clearance_obtained": True}}
TODAY = date(2026, 10, 11)


def _days(plan_type="3_day", exercise_id=1, sets=3, reps=10):
    return [
        {
            "day_number": day["day_number"],
            "primary": [{"exercise_id": exercise_id, "sets": sets, "reps": reps} for _ in day["primary"]],
            "secondary": [{"exercise_id": exercise_id, "sets": sets, "reps": reps} for _ in day["secondary"]],
        }
        for day in DAY_TEMPLATES[plan_type]["schedule"]
        if not day["is_rest_day"]
    ]


def _plan_body(**overrides):
    body = {"plan_type": "3_day", "start_date": "2026-10-13", "days": _days(), "coach_notes": " Go easy "}
    body.update(overrides)
    return body


@pytest.fixture
def admin(app_module, monkeypatch):
    """(client, controller module) with repos and the preprocessor mocked."""
    import backend.controllers.admin_plan_controller as controller

    monkeypatch.setenv("ADMIN_API_KEY", ADMIN_KEY)
    monkeypatch.setenv("APP_BASE_URL", "https://coach.example")
    repo = controller.plan_repo
    monkeypatch.setattr(controller.exercise_repo, "list_exercises", MagicMock(return_value=EXERCISES))
    monkeypatch.setattr(repo, "get_unfinished_plan", MagicMock(return_value=None))
    monkeypatch.setattr(repo, "user_exists", MagicMock(return_value=False))
    monkeypatch.setattr(repo, "get_profile", MagicMock(return_value=PROFILE))
    monkeypatch.setattr(repo, "upsert_user_profile", MagicMock())
    monkeypatch.setattr(repo, "create_plan", MagicMock(return_value={"id": 77}))
    monkeypatch.setattr(controller, "app_today", lambda: TODAY)
    monkeypatch.setattr(
        controller, "generate_user_profile", MagicMock(return_value={"user_id": "usr_placeholder", "goals": {}})
    )
    monkeypatch.setattr(controller.auth_repo, "list_credential_ids", MagicMock(return_value=[]))
    monkeypatch.setattr(controller.auth_repo, "create_enrollment_token", MagicMock())
    return app_module.app.test_client(), controller


# --- auth --------------------------------------------------------------------

@pytest.mark.parametrize("method, path", [
    ("post", "/api/admin/users/profile"),
    ("get", "/api/admin/plan-builder"),
    ("post", "/api/admin/users/usr_new/initial-plan"),
])
def test_endpoints_require_admin_key(admin, method, path):
    client, controller = admin
    assert getattr(client, method)(path, json={}).status_code == 401
    controller.generate_user_profile.assert_not_called()
    controller.plan_repo.create_plan.assert_not_called()


# --- POST /api/admin/users/profile ---------------------------------------------

def test_profile_generates_and_upserts_with_callers_user_id(admin):
    client, controller = admin

    response = client.post(
        "/api/admin/users/profile",
        json={"user_id": "usr_new", "name": "  Asha Raman ", "raw_user_text": "52yo, sore knee"},
        headers=ADMIN_HEADERS,
    )

    assert response.status_code == 200
    expected = {"user_id": "usr_new", "goals": {}}
    assert response.get_json() == {
        "user_id": "usr_new", "name": "Asha Raman", "profile": expected, "user_created": True,
    }
    controller.generate_user_profile.assert_called_once_with("52yo, sore knee")
    controller.plan_repo.upsert_user_profile.assert_called_once_with("usr_new", expected, "Asha Raman")


def test_profile_for_existing_user_reports_not_created(admin):
    client, controller = admin
    controller.plan_repo.user_exists.return_value = True

    response = client.post(
        "/api/admin/users/profile", json={"user_id": "usr_new", "name": "Asha", "raw_user_text": "x"}, headers=ADMIN_HEADERS
    )

    assert response.status_code == 200
    assert response.get_json()["user_created"] is False


def test_profile_conflicts_with_unfinished_plan_before_calling_llm(admin):
    client, controller = admin
    controller.plan_repo.get_unfinished_plan.return_value = {"id": 5, "completed": False, "plan": {}}

    response = client.post(
        "/api/admin/users/profile", json={"user_id": "usr_new", "name": "Asha", "raw_user_text": "x"}, headers=ADMIN_HEADERS
    )

    assert response.status_code == 409
    assert response.get_json()["plan_id"] == 5
    controller.generate_user_profile.assert_not_called()
    controller.plan_repo.upsert_user_profile.assert_not_called()


def test_profile_preprocessor_failure_returns_502(admin):
    client, controller = admin
    controller.generate_user_profile.side_effect = ValueError("bad json")

    response = client.post(
        "/api/admin/users/profile", json={"user_id": "usr_new", "name": "Asha", "raw_user_text": "x"}, headers=ADMIN_HEADERS
    )

    assert response.status_code == 502
    controller.plan_repo.upsert_user_profile.assert_not_called()


def test_profile_save_failure_returns_500(admin):
    client, controller = admin
    controller.plan_repo.upsert_user_profile.side_effect = RuntimeError("db unreachable")

    response = client.post(
        "/api/admin/users/profile", json={"user_id": "usr_new", "name": "Asha", "raw_user_text": "x"}, headers=ADMIN_HEADERS
    )

    assert response.status_code == 500


@pytest.mark.parametrize("body", [
    {"name": "Asha", "raw_user_text": "x"},
    {"user_id": "", "name": "Asha", "raw_user_text": "x"},
    {"user_id": "has space", "name": "Asha", "raw_user_text": "x"},
    {"user_id": "x" * 65, "name": "Asha", "raw_user_text": "x"},
    {"user_id": 123, "name": "Asha", "raw_user_text": "x"},
    {"user_id": "usr_new", "raw_user_text": "x"},
    {"user_id": "usr_new", "name": "   ", "raw_user_text": "x"},
    {"user_id": "usr_new", "name": "x" * 101, "raw_user_text": "x"},
    {"user_id": "usr_new", "name": 7, "raw_user_text": "x"},
    {"user_id": "usr_new", "name": "Asha"},
    {"user_id": "usr_new", "name": "Asha", "raw_user_text": "   "},
])
def test_profile_rejects_invalid_payload(admin, body):
    client, controller = admin

    response = client.post("/api/admin/users/profile", json=body, headers=ADMIN_HEADERS)

    assert response.status_code == 400
    controller.generate_user_profile.assert_not_called()


# --- GET /api/admin/plan-builder -----------------------------------------------

def test_plan_builder_returns_templates_and_exercises(admin):
    client, _ = admin

    response = client.get("/api/admin/plan-builder", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    assert response.get_json() == {"templates": DAY_TEMPLATES, "exercises": EXERCISES}


# --- POST /api/admin/users/<user_id>/initial-plan ----------------------------

def _post_plan(client, body, user_id="usr_new"):
    return client.post(f"/api/admin/users/{user_id}/initial-plan", json=body, headers=ADMIN_HEADERS)


def test_initial_plan_saves_plan_and_mints_link(admin):
    client, controller = admin

    response = _post_plan(client, _plan_body())

    assert response.status_code == 201
    data = response.get_json()
    assert data["user_id"] == "usr_new"
    assert data["plan_id"] == 77
    assert data["enrollment"]["url"].startswith("https://coach.example/enroll?token=")

    user_id, plan, start_date = controller.plan_repo.create_plan.call_args.args
    assert user_id == "usr_new"
    assert start_date == date(2026, 10, 13)
    assert plan["plan_type"] == "3_day"
    assert plan["coach_notes"] == "Go easy"
    assert plan["plan_selection_reason"] == "Built manually by coach"
    assert plan["medical_clearance_warning"] is None
    day1 = plan["schedule"][0]
    assert [e["slot"] for e in day1["primary"]] == ["Hinge", "Push (Horizontal)", "Pull (Vertical)"]
    assert day1["primary"][0] == {
        "exercise_id": 1, "slot": "Hinge", "sets": 3, "reps": "10", "rep_range": "8-15", "note": None,
    }
    assert plan["schedule"][1]["is_rest_day"] is True
    assert plan["schedule"][1]["primary"] == []


def test_initial_plan_rep_range_null_when_exercise_has_no_bounds(admin):
    client, controller = admin

    response = _post_plan(client, _plan_body(days=_days(exercise_id=2)))

    assert response.status_code == 201
    plan = controller.plan_repo.create_plan.call_args.args[1]
    assert plan["schedule"][0]["primary"][0]["rep_range"] is None


def test_initial_plan_keeps_slot_notes(admin):
    client, controller = admin
    days = _days()
    days[0]["primary"][0]["note"] = "  Slow tempo "

    assert _post_plan(client, _plan_body(days=days)).status_code == 201
    plan = controller.plan_repo.create_plan.call_args.args[1]
    assert plan["schedule"][0]["primary"][0]["note"] == "Slow tempo"


def test_initial_plan_warns_when_client_lacks_medical_clearance(admin):
    client, controller = admin
    controller.plan_repo.get_profile.return_value = {"health": {"medical_clearance_obtained": False}}

    assert _post_plan(client, _plan_body()).status_code == 201
    plan = controller.plan_repo.create_plan.call_args.args[1]
    assert plan["medical_clearance_warning"]


def test_initial_plan_unknown_user_returns_404(admin):
    client, controller = admin
    controller.plan_repo.get_profile.return_value = None

    assert _post_plan(client, _plan_body()).status_code == 404
    controller.plan_repo.create_plan.assert_not_called()


def test_initial_plan_conflicts_with_unfinished_plan(admin):
    client, controller = admin
    controller.plan_repo.get_unfinished_plan.return_value = {"id": 5, "completed": False, "plan": {}}

    response = _post_plan(client, _plan_body())

    assert response.status_code == 409
    assert response.get_json()["plan_id"] == 5
    controller.plan_repo.create_plan.assert_not_called()


def test_initial_plan_can_start_today(admin):
    client, controller = admin

    assert _post_plan(client, _plan_body(start_date="2026-10-11")).status_code == 201
    assert controller.plan_repo.create_plan.call_args.args[2] == TODAY


@pytest.mark.parametrize("overrides", [
    {"start_date": None},
    {"start_date": "13/10/2026"},
    {"start_date": "2026-10-10"},                           # in the past
    {"plan_type": "5_day"},
    {"coach_notes": 5},
    {"days": "nope"},
    {"days": _days()[1:]},                                  # a training day missing
    {"days": _days() + _days()[:1]},                        # a day twice
    {"days": _days() + [{"day_number": 2, "primary": [], "secondary": []}]},  # rest day
    {"days": [{**d, "secondary": []} for d in _days()]},    # slot count mismatch
    {"days": _days(exercise_id=999)},                       # unknown exercise
    {"days": _days(exercise_id=True)},
    {"days": _days(sets=0)},
    {"days": _days(sets=11)},
    {"days": _days(reps=True)},
    {"days": _days(reps="10")},
])
def test_initial_plan_rejects_invalid_payload(admin, overrides):
    client, controller = admin

    response = _post_plan(client, _plan_body(**overrides))

    assert response.status_code == 400
    assert "error" in response.get_json()
    controller.plan_repo.create_plan.assert_not_called()


def test_initial_plan_save_failure_returns_500_without_minting_link(admin):
    client, controller = admin
    controller.plan_repo.create_plan.side_effect = RuntimeError("db unreachable")

    assert _post_plan(client, _plan_body()).status_code == 500
    controller.auth_repo.create_enrollment_token.assert_not_called()


def test_initial_plan_skips_link_for_enrolled_user(admin):
    client, controller = admin
    controller.auth_repo.list_credential_ids.return_value = ["cred-1"]

    response = _post_plan(client, _plan_body())

    assert response.status_code == 201
    assert response.get_json()["enrollment"] is None
    controller.auth_repo.create_enrollment_token.assert_not_called()


def test_initial_plan_still_succeeds_when_link_minting_fails(admin):
    client, controller = admin
    controller.auth_repo.create_enrollment_token.side_effect = RuntimeError("db unreachable")

    response = _post_plan(client, _plan_body())

    assert response.status_code == 201
    assert response.get_json()["enrollment"] is None
