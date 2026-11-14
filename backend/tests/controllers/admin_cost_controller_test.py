"""Tests for the AI cost dashboard endpoint (admin_cost_controller.py)."""
from unittest.mock import MagicMock

import pytest

ADMIN = {"X-Admin-Key": "test-admin-key"}


def _row(user_id, provider, feature, inr, session_id=None, calls=1, at="2026-11-14T10:00:00+00:00"):
    return {"user_id": user_id, "session_id": session_id, "provider": provider, "feature": feature,
            "calls": calls, "cost_inr_total": inr, "created_at": at}


ROWS = [
    _row("usr_1", "anthropic", "summary_questions", 3.0, session_id=81),
    _row("usr_1", "sarvam", "summary_tts", 2.0, session_id=81),
    _row("usr_1", "anthropic", "summary_questions", 2.5, session_id=84, at="2026-11-15T10:00:00+00:00"),
    _row("usr_1", "anthropic", "profile_generation", 1.0),           # not tied to a workout
    _row("usr_2", "anthropic", "coach_suggestions", 7.0, session_id=90),
    _row(None, "anthropic", "plan_generation", 4.0, calls=15),
    _row("usr_2", "sarvam", "reply_stt", None, session_id=90),       # cost unknown counts as 0
]


def test_summarize_costs_per_client_and_feature():
    from backend.controllers.admin_cost_controller import summarize_costs

    result = summarize_costs(ROWS, {"usr_1": "Sasikala", "usr_2": "Asha"}, 30)

    assert (result["total_inr"], result["claude_inr"], result["sarvam_inr"]) == (19.5, 17.5, 2.0)
    assert result["calls"] == 21
    assert result["active_clients"] == 2
    assert result["per_client_inr"] == 7.75            # (8.5 + 7) / 2, unattributed left out
    assert result["by_feature"][0] == {"provider": "anthropic", "feature": "coach_suggestions", "calls": 1, "inr": 7.0}

    first, second, third = result["clients"]
    assert (first["user_id"], first["name"], first["total_inr"]) == ("usr_1", "Sasikala", 8.5)
    assert (first["claude_inr"], first["sarvam_inr"]) == (6.5, 2.0)
    assert (first["workouts"], first["per_workout_inr"]) == (2, 3.75)   # 7.5 across sessions 81 and 84
    assert first["last_at"] == "2026-11-15T10:00:00+00:00"
    assert first["by_feature"][0] == {"provider": "anthropic", "feature": "summary_questions", "calls": 2, "inr": 5.5}
    assert (second["user_id"], second["total_inr"]) == ("usr_2", 7.0)
    assert (third["user_id"], third["per_workout_inr"]) == ("(unattributed)", None)


def test_summarize_costs_with_no_usage():
    from backend.controllers.admin_cost_controller import summarize_costs

    result = summarize_costs([], {}, 30)

    assert (result["total_inr"], result["clients"], result["per_client_inr"]) == (0, [], None)


@pytest.fixture
def ctl(app_module, monkeypatch):
    import backend.controllers.admin_cost_controller as controller

    monkeypatch.setenv("ADMIN_API_KEY", "test-admin-key")
    monkeypatch.setattr(controller, "_fetch_usage", MagicMock(return_value=ROWS))
    monkeypatch.setattr(controller.plan_repo, "list_user_profiles", MagicMock(return_value=[
        {"user_id": "usr_1", "name": "Sasikala"},
    ]))
    return app_module.app.test_client(), controller


def test_costs_endpoint_requires_the_admin_key(ctl):
    client, _ = ctl
    assert client.get("/api/admin/costs").status_code == 401


def test_costs_endpoint_defaults_to_30_days_without_dry_runs(ctl):
    client, controller = ctl

    body = client.get("/api/admin/costs", headers=ADMIN).get_json()

    assert body["days"] == 30 and body["include_dry_runs"] is False
    assert body["clients"][0]["name"] == "Sasikala"
    assert controller._fetch_usage.call_args.args[1] is False


@pytest.mark.parametrize("query", ["days=0", "days=400", "days=abc"])
def test_costs_endpoint_rejects_a_bad_range(ctl, query):
    client, _ = ctl
    assert client.get(f"/api/admin/costs?{query}", headers=ADMIN).status_code == 400


def test_costs_endpoint_can_include_dry_runs(ctl):
    client, controller = ctl
    client.get("/api/admin/costs?days=7&include_dry_runs=1", headers=ADMIN)
    assert controller._fetch_usage.call_args.args[1] is True
