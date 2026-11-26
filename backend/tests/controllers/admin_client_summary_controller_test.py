"""Tests for the client summary endpoints (backend/controllers/
admin_client_summary_controller.py). The service is mocked; Supabase is
mocked by conftest.app_module."""
from unittest.mock import MagicMock

import pytest

ADMIN = {"X-Admin-Key": "test-admin-key"}
ROW = {"version": 2, "text": "SUMMARY", "created_at": "2026-11-26T12:00:00+00:00", "covers_from": None,
       "covers_until": "2026-11-26T12:00:00+00:00", "word_count": 1, "model": "m", "rebuilt": False,
       "storage_path": "u1/v2.txt", "state_hash": "h", "user_id": "u1"}


@pytest.fixture
def ctl(app_module, monkeypatch):
    import backend.controllers.admin_client_summary_controller as controller

    monkeypatch.setenv("ADMIN_API_KEY", "test-admin-key")
    return app_module.app.test_client(), controller


def test_endpoints_require_the_admin_key(ctl):
    client, _ = ctl
    assert client.get("/api/admin/users/u1/summary").status_code == 401
    assert client.post("/api/admin/users/u1/summary").status_code == 401


def test_get_returns_the_latest_without_internal_fields(ctl, monkeypatch):
    client, controller = ctl
    monkeypatch.setattr(controller, "latest_summary", MagicMock(return_value=ROW))
    body = client.get("/api/admin/users/u1/summary", headers=ADMIN).get_json()
    assert body["summary"]["text"] == "SUMMARY"
    assert "storage_path" not in body["summary"] and "state_hash" not in body["summary"]


def test_get_with_no_summary_yet(ctl, monkeypatch):
    client, controller = ctl
    monkeypatch.setattr(controller, "latest_summary", MagicMock(return_value=None))
    assert client.get("/api/admin/users/u1/summary", headers=ADMIN).get_json() == {"summary": None}


def test_post_passes_rebuild_and_returns_nothing_new(ctl, monkeypatch):
    client, controller = ctl
    run = MagicMock(return_value={"summary": ROW, "nothing_new": True})
    monkeypatch.setattr(controller, "summarize_client", run)
    body = client.post("/api/admin/users/u1/summary", headers=ADMIN, json={"rebuild": True}).get_json()
    assert body["nothing_new"] is True and body["summary"]["version"] == 2
    assert run.call_args.kwargs["rebuild"] is True
    client.post("/api/admin/users/u1/summary", headers=ADMIN)
    assert run.call_args.kwargs["rebuild"] is False


def test_post_errors(ctl, monkeypatch):
    client, controller = ctl
    from backend.client_summary.service import ClientNotFoundError

    monkeypatch.setattr(controller, "summarize_client", MagicMock(side_effect=ClientNotFoundError("u1")))
    assert client.post("/api/admin/users/u1/summary", headers=ADMIN).status_code == 404
    monkeypatch.setattr(controller, "summarize_client", MagicMock(side_effect=Exception('duplicate key "23505"')))
    assert client.post("/api/admin/users/u1/summary", headers=ADMIN).status_code == 409
    monkeypatch.setattr(controller, "summarize_client", MagicMock(side_effect=RuntimeError("model down")))
    assert client.post("/api/admin/users/u1/summary", headers=ADMIN).status_code == 502
