"""Tests for the AI Coach endpoints (backend/controllers/
admin_coach_agent_controller.py). The repositories and the Claude call are
mocked; Supabase is mocked by conftest.app_module."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

ADMIN = {"X-Admin-Key": "test-admin-key"}
FUTURE = "2999-01-01"


@pytest.fixture
def ctl(app_module, monkeypatch):
    import backend.controllers.admin_coach_agent_controller as controller

    monkeypatch.setenv("ADMIN_API_KEY", "test-admin-key")
    monkeypatch.setattr(controller, "coach_repo", MagicMock())
    controller.coach_repo.get_exercises.return_value = {
        10: {"id": 10, "name": "Squat", "min_reps": 6, "max_reps": 12, "is_time_based": False},
        30: {"id": 30, "name": "Sit to stand", "min_reps": 8, "max_reps": 15, "is_time_based": False},
    }
    for name in ("get_session_exercise_for_edit", "update_session_exercise_prescription", "set_session_exercise_skipped"):
        monkeypatch.setattr(controller.plan_repo, name, MagicMock())
    monkeypatch.setattr(controller.exercise_repo, "get_exercise", MagicMock())
    return app_module.app.test_client(), controller


def _session(**overrides):
    session = {"id": 88, "kind": "strength", "scheduled_date": FUTURE, "completed_at": None,
               "plans": {"user_id": "usr_1", "completed": False}}
    session.update(overrides)
    return session


FACTS = {"user_id": "usr_1", "client_texts": [], "exercises": {1: {
    "session_exercise_id": 1, "exercise_id": 10, "name": "Squat", "is_time_based": False, "sets": 3,
    "reps": [10, 10, 10], "reps_stored": "10", "min": 6, "max": 12, "actionable": True,
    "options": {"progression": {}, "regression": {}},
}}}


def _stored_row(**overrides):
    row = {"id": 500, "session_exercise_id": 1, "action": "adjust", "status": "pending", "reason": "R",
           "evidence": [], "proposed_sets": 3, "proposed_reps": "11", "proposed_exercise_id": None,
           "before": {"exercise_id": 10, "name": "Squat", "sets": 3, "reps": "10"}}
    row.update(overrides)
    return row


def test_endpoints_require_the_admin_key(ctl):
    client, _ = ctl
    assert client.post("/api/admin/sessions/88/suggestions").status_code == 401
    assert client.post("/api/admin/exercise-suggestions/1/accept").status_code == 401


def test_create_runs_the_agent_validates_and_stores(ctl, monkeypatch):
    client, controller = ctl
    controller.coach_repo.get_session.return_value = _session()
    monkeypatch.setattr(controller, "build_context", MagicMock(return_value=({"ctx": 1}, FACTS)))
    from backend.coach_agent.agent import Evidence, ExerciseSuggestion, SessionSuggestions
    result = SessionSuggestions(overview=" Looks fine. ", exercises=[ExerciseSuggestion(
        session_exercise_id=1, action="adjust", sets=3, reps=[11, 11, 11], to_exercise_id=None, reason="Easy.",
        evidence=[Evidence(source="rpe", quote="RPE 6", session_id=79)],
    )])
    monkeypatch.setattr(controller.agent, "suggest", MagicMock(return_value=result))
    controller.coach_repo.save_run.side_effect = lambda sid, uid, overview, model, rows: {
        "id": 9, "overview": overview, "model": model, "exercise_suggestions": [{**rows[0], "id": 500}],
    }

    response = client.post("/api/admin/sessions/88/suggestions", headers=ADMIN)

    assert response.status_code == 200
    body = response.get_json()
    assert body["run"]["overview"] == "Looks fine."
    [suggestion] = body["suggestions"]
    assert (suggestion["action"], suggestion["status"]) == ("adjust", "pending")
    assert suggestion["current"] == {"exercise_id": 10, "name": "Squat", "sets": 3, "reps": "10",
                                     "rep_range": "6-12", "is_time_based": False}
    assert (suggestion["proposed"]["sets"], suggestion["proposed"]["reps"]) == (3, "11")
    controller.agent.suggest.assert_called_once_with({"ctx": 1}, user_id="usr_1")


@pytest.mark.parametrize("session, status", [
    (None, 404),
    (_session(kind="cardio"), 409),
    (_session(completed_at="2026-11-01T00:00:00+00:00"), 409),
])
def test_create_refuses_what_it_cannot_review(ctl, session, status):
    client, controller = ctl
    controller.coach_repo.get_session.return_value = session
    assert client.post("/api/admin/sessions/88/suggestions", headers=ADMIN).status_code == status


def test_create_reports_an_agent_failure(ctl, monkeypatch):
    client, controller = ctl
    controller.coach_repo.get_session.return_value = _session()
    monkeypatch.setattr(controller, "build_context", MagicMock(return_value=({}, FACTS)))
    monkeypatch.setattr(controller.agent, "suggest", MagicMock(side_effect=TimeoutError()))

    assert client.post("/api/admin/sessions/88/suggestions", headers=ADMIN).status_code == 502
    controller.coach_repo.save_run.assert_not_called()


def _edit_row(**overrides):
    row = {"id": 1, "exercise_id": 10, "sets": 3, "reps": "10", "skipped": False, "session_exercise_set_logs": [],
           "sessions": {"scheduled_date": FUTURE, "completed_at": None, "plans": {"completed": False}}}
    row.update(overrides)
    return row


def test_accept_adjust_applies_it(ctl):
    client, controller = ctl
    controller.coach_repo.get_suggestion.return_value = _stored_row()
    controller.plan_repo.get_session_exercise_for_edit.return_value = _edit_row()

    response = client.post("/api/admin/exercise-suggestions/500/accept", headers=ADMIN)

    assert response.status_code == 200
    assert response.get_json()["exercise"] == {"id": 1, "sets": 3, "reps": "11"}
    controller.plan_repo.update_session_exercise_prescription.assert_called_once_with(1, 3, "11")
    controller.coach_repo.set_suggestion_status.assert_called_once_with(500, "accepted")


def test_accept_regress_swaps_the_exercise(ctl):
    client, controller = ctl
    controller.coach_repo.get_suggestion.return_value = _stored_row(action="regress", proposed_exercise_id=30,
                                                                   proposed_reps="15")
    controller.plan_repo.get_session_exercise_for_edit.return_value = _edit_row()
    swap = {"id": 30, "name": "Sit to stand", "movement_type": "squat", "orientation": "", "dominant": True,
            "is_time_based": False, "equipment": [], "video_url": "", "min_reps": 8, "max_reps": 15}
    controller.exercise_repo.get_exercise.return_value = swap

    response = client.post("/api/admin/exercise-suggestions/500/accept", headers=ADMIN)

    assert response.status_code == 200
    assert response.get_json()["exercise"]["exercise"]["name"] == "Sit to stand"
    controller.plan_repo.update_session_exercise_prescription.assert_called_once_with(1, 3, "15", exercise=swap)


def test_accept_skip_marks_it_skipped(ctl):
    client, controller = ctl
    controller.coach_repo.get_suggestion.return_value = _stored_row(action="skip", reason="Knee pain.")
    controller.plan_repo.get_session_exercise_for_edit.return_value = _edit_row()

    response = client.post("/api/admin/exercise-suggestions/500/accept", headers=ADMIN)

    assert response.get_json()["exercise"] == {"id": 1, "skipped": True, "skip_reason": "Knee pain."}
    controller.plan_repo.set_session_exercise_skipped.assert_called_once_with(1, True, "Knee pain.")


@pytest.mark.parametrize("suggestion, row, why", [
    (_stored_row(status="rejected"), _edit_row(), "already rejected"),
    (_stored_row(), _edit_row(session_exercise_set_logs=[{"set_number": 1}]), "logged sets"),
    (_stored_row(), _edit_row(reps="12"), "changed after"),
    (_stored_row(), _edit_row(skipped=True), "changed after"),
    (_stored_row(), _edit_row(sessions={"scheduled_date": "2020-01-01", "completed_at": None,
                                        "plans": {"completed": False}}), "upcoming"),
])
def test_accept_rechecks_the_workout_as_it_is_now(ctl, suggestion, row, why):
    client, controller = ctl
    controller.coach_repo.get_suggestion.return_value = suggestion
    controller.plan_repo.get_session_exercise_for_edit.return_value = row

    response = client.post("/api/admin/exercise-suggestions/500/accept", headers=ADMIN)

    assert response.status_code == 409
    assert why in response.get_json()["error"]
    controller.plan_repo.update_session_exercise_prescription.assert_not_called()


def test_reject(ctl):
    client, controller = ctl
    controller.coach_repo.get_suggestion.return_value = _stored_row()

    response = client.post("/api/admin/exercise-suggestions/500/reject", headers=ADMIN)

    assert response.get_json() == {"id": 500, "status": "rejected"}
    controller.coach_repo.set_suggestion_status.assert_called_once_with(500, "rejected")


def test_latest_returns_an_empty_run_when_there_is_none(ctl):
    client, controller = ctl
    controller.coach_repo.get_latest_run.return_value = None
    assert client.get("/api/admin/sessions/88/suggestions", headers=ADMIN).get_json() == {"run": None, "suggestions": []}


def test_patch_restores_a_skipped_exercise(ctl):
    client, controller = ctl
    controller.plan_repo.get_session_exercise_for_edit.return_value = _edit_row(skipped=True)

    response = client.patch("/api/admin/session-exercises/1", json={"skipped": False}, headers=ADMIN)

    assert response.get_json() == {"id": 1, "skipped": False, "skip_reason": None}
    controller.plan_repo.set_session_exercise_skipped.assert_called_once_with(1, False)
