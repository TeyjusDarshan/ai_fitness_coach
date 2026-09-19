"""Tests for the /webhooks/whatsapp controller.

Supabase and the WhatsApp Cloud API are mocked (see conftest.app_module):
whatsapp_webhook_controller's own module-level plan_repo/whatsapp_client
instances have their methods swapped for MagicMocks so these tests exercise
only the webhook's own parsing/routing logic.
"""
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def controller(app_module):
    # Imported lazily, after app_module has imported backend.app (and so
    # backend.controllers.whatsapp_webhook_controller) inside its patched
    # context — a top-level import here would run before that and hit the
    # real, unset WHATSAPP_ACCESS_TOKEN/PHONE_NUMBER_ID env vars.
    import backend.controllers.whatsapp_webhook_controller as module
    return module


def _inbound_payload(text: str, sender: str = "919876543210"):
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{"from": sender, "type": "text", "text": {"body": text}}],
                },
            }],
        }],
    }


def test_receive_message_with_ready_analysis_sends_audio(app_module, controller, monkeypatch):
    monkeypatch.setattr(
        controller.plan_repo, "get_day_analysis",
        MagicMock(return_value={"analysis": "...", "audio_url": "https://example.com/a.ogg"}),
    )
    monkeypatch.setattr(controller.whatsapp_client, "send_audio", MagicMock())
    monkeypatch.setattr(controller.whatsapp_client, "send_text", MagicMock())

    client = app_module.app.test_client()
    response = client.post(
        "/webhooks/whatsapp",
        json=_inbound_payload("*Workout Summary*\nSession ID: 12\nDay: 1\n"),
    )

    assert response.status_code == 200
    controller.plan_repo.get_day_analysis.assert_called_once_with(12, 1)
    controller.whatsapp_client.send_audio.assert_called_once_with(
        "919876543210", "https://example.com/a.ogg"
    )
    controller.whatsapp_client.send_text.assert_not_called()


def test_receive_message_with_pending_analysis_sends_holding_text(app_module, controller, monkeypatch):
    monkeypatch.setattr(controller.plan_repo, "get_day_analysis", MagicMock(return_value=None))
    monkeypatch.setattr(controller.whatsapp_client, "send_audio", MagicMock())
    monkeypatch.setattr(controller.whatsapp_client, "send_text", MagicMock())

    client = app_module.app.test_client()
    response = client.post(
        "/webhooks/whatsapp",
        json=_inbound_payload("Session ID: 12\nDay: 1\n"),
    )

    assert response.status_code == 200
    controller.whatsapp_client.send_text.assert_called_once_with(
        "919876543210", controller.ANALYSIS_PENDING_MESSAGE
    )
    controller.whatsapp_client.send_audio.assert_not_called()


def test_receive_message_without_session_fields_is_ignored(app_module, controller, monkeypatch):
    monkeypatch.setattr(controller.plan_repo, "get_day_analysis", MagicMock())
    monkeypatch.setattr(controller.whatsapp_client, "send_text", MagicMock())
    monkeypatch.setattr(controller.whatsapp_client, "send_audio", MagicMock())

    client = app_module.app.test_client()
    response = client.post("/webhooks/whatsapp", json=_inbound_payload("hey coach, question!"))

    assert response.status_code == 200
    controller.plan_repo.get_day_analysis.assert_not_called()
    controller.whatsapp_client.send_text.assert_not_called()
    controller.whatsapp_client.send_audio.assert_not_called()


def test_verify_webhook_matching_token_echoes_challenge(app_module, controller, monkeypatch):
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "shared-secret")

    client = app_module.app.test_client()
    response = client.get("/webhooks/whatsapp", query_string={
        "hub.mode": "subscribe",
        "hub.verify_token": "shared-secret",
        "hub.challenge": "12345",
    })

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "12345"


def test_verify_webhook_wrong_token_is_rejected(app_module, controller, monkeypatch):
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "shared-secret")

    client = app_module.app.test_client()
    response = client.get("/webhooks/whatsapp", query_string={
        "hub.mode": "subscribe",
        "hub.verify_token": "wrong",
        "hub.challenge": "12345",
    })

    assert response.status_code == 403
