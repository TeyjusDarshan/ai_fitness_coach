"""Tests for the weight endpoints (weight_controller.py) and the coach's
target edit being recorded as a change (diet_controller.py). The view
itself is tested in diet/test/weight_service_test.py."""
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

ADMIN = {"X-Admin-Key": "test-admin-key"}
SETUP = {"height_cm": 160, "weight_kg": 74.0, "age": 52, "goal": "lose", "target_weight_kg": 68.0,
         "weekly_change_kg": 0.4, "completed_at": "2026-10-05T05:00:00+00:00"}
PROFILE = {"user_id": "usr_1", "name": "Priya", "gender": "female", "timezone": "Asia/Kolkata",
           "whatsapp_number": "919876543210", "diet_setup": SETUP, "nutrition_targets": {"energy_kcal": 1500},
           "weight_goal": None, "weight_goal_kg": None}
PENDING = {"id": 7, "user_id": "usr_1", "week_id": 40, "status": "pending", "new_goal": None,
           "from_targets": {"energy_kcal": 1500}, "to_targets": {"energy_kcal": 1350, "protein_g": 80,
                                                                  "carbs_g": 150, "fat_g": 38, "fibre_g": 25}}


@pytest.fixture
def ctl(app_module, monkeypatch):
    import backend.controllers.diet_controller as diet
    import backend.controllers.weight_controller as controller

    repo = MagicMock()
    repo.get_profile.return_value = dict(PROFILE)
    repo.first_reading.return_value = None
    repo.list_readings.return_value = []
    repo.list_weeks.return_value = [{"id": 40, "week_start": "2026-11-16", "outcome": "lower_calories",
                                     "classification": "stalled"}]
    repo.list_changes.return_value = [PENDING]
    repo.get_change.return_value = dict(PENDING)
    repo.decide_change.return_value = True
    repo.reply_window_open.return_value = True
    monkeypatch.setenv("ADMIN_API_KEY", "test-admin-key")
    monkeypatch.setattr(controller, "weight_repo", repo)
    monkeypatch.setattr(controller, "whatsapp_client", MagicMock())
    monkeypatch.setattr(diet.diet_repo, "is_enabled", lambda user_id: True)
    controller.repo = repo
    return controller


def test_her_view_is_her_own_and_takes_a_range(ctl, sign_in):
    client = sign_in("usr_1")
    body = client.get("/api/users/usr_1/weight?weeks=4").get_json()
    assert body["goal"] == "lose" and body["target_weight_kg"] == 68.0
    assert body["status"] == {"week_start": "2026-11-16", "outcome": "lower_calories", "classification": "stalled"}
    assert set(body["chart"]) == {"unlocked", "readings_needed", "unlocks_on", "weeks"}
    assert client.get("/api/users/usr_2/weight").status_code == 403
    assert client.get("/api/users/usr_1/weight?weeks=lots").status_code == 400
    assert client.get("/api/users/usr_1/weight?weeks=all").status_code == 200


def test_her_view_needs_the_diet_setup(ctl, sign_in):
    ctl.repo.get_profile.return_value = {**PROFILE, "diet_setup": None}
    assert sign_in("usr_1").get("/api/users/usr_1/weight").status_code == 409


def test_coach_view_has_weeks_readings_and_changes(ctl, app_module):
    client = app_module.app.test_client()
    assert client.get("/api/admin/users/usr_1/weight").status_code == 401
    ctl.repo.list_readings.return_value = [{"measured_on": "2026-11-25", "weight_kg": 72.1, "source": "whatsapp_text",
                                            "raw": "72.1"}]
    body = client.get("/api/admin/users/usr_1/weight", headers=ADMIN).get_json()
    assert body["readings"] == [{"date": "2026-11-25", "weight_kg": 72.1, "source": "whatsapp_text", "raw": "72.1"}]
    assert body["weeks"][0]["id"] == 40 and body["changes"][0]["id"] == 7


def test_accepting_applies_the_targets_and_tells_her(ctl, app_module):
    client = app_module.app.test_client()
    body = client.post("/api/admin/nutrition-target-changes/7/accept", headers=ADMIN).get_json()
    assert body["status"] == "accepted" and body["targets"]["energy_kcal"] == 1350 and body["notified"] is True
    ctl.repo.set_targets.assert_called_once_with("usr_1", PENDING["to_targets"])
    ctl.repo.set_weight_goal.assert_not_called()
    assert "1500 → 1350" in ctl.whatsapp_client.send_text.call_args.args[1]


def test_accepting_a_goal_switch_makes_her_a_maintain_client(ctl, app_module):
    ctl.repo.get_change.return_value = {**PENDING, "new_goal": "maintain", "new_goal_kg": 68.4}
    app_module.app.test_client().post("/api/admin/nutrition-target-changes/7/accept", headers=ADMIN)
    ctl.repo.set_weight_goal.assert_called_once_with("usr_1", "maintain", 68.4)


def test_no_message_when_her_window_is_closed(ctl, app_module):
    ctl.repo.reply_window_open.return_value = False
    body = app_module.app.test_client().post("/api/admin/nutrition-target-changes/7/accept", headers=ADMIN).get_json()
    assert body["notified"] is False
    ctl.whatsapp_client.send_text.assert_not_called()


def test_a_change_is_decided_once(ctl, app_module):
    client = app_module.app.test_client()
    ctl.repo.decide_change.return_value = False
    assert client.post("/api/admin/nutrition-target-changes/7/accept", headers=ADMIN).status_code == 409
    assert client.post("/api/admin/nutrition-target-changes/7/reject", headers=ADMIN).status_code == 409
    ctl.repo.get_change.return_value = None
    assert client.post("/api/admin/nutrition-target-changes/9/reject", headers=ADMIN).status_code == 404
    ctl.repo.set_targets.assert_not_called()


def test_rejecting(ctl, app_module):
    body = app_module.app.test_client().post("/api/admin/nutrition-target-changes/7/reject", headers=ADMIN).get_json()
    assert body == {"id": 7, "status": "rejected"}
    ctl.repo.decide_change.assert_called_once_with(7, "rejected")


def test_the_coachs_own_target_edit_is_recorded_as_a_change(app_module, monkeypatch):
    import backend.controllers.diet_controller as diet
    monkeypatch.setenv("ADMIN_API_KEY", "test-admin-key")
    monkeypatch.setattr(diet.diet_repo, "get_targets", lambda user_id: {"energy_kcal": 1500})
    monkeypatch.setattr(diet.diet_repo, "set_targets", lambda user_id, targets: True)
    weight_repo = MagicMock()
    monkeypatch.setattr(diet, "weight_repo", weight_repo)
    app_module.app.test_client().patch("/api/admin/users/usr_1/nutrition-targets",
                                       json={"energy_kcal": 1400}, headers=ADMIN)
    weight_repo.supersede_pending.assert_called_once_with("usr_1")
    change = weight_repo.create_change.call_args.args[0]
    assert (change["source"], change["status"]) == ("coach_manual", "accepted")
    assert change["from_targets"]["energy_kcal"] == 1500 and change["to_targets"]["energy_kcal"] == 1400
