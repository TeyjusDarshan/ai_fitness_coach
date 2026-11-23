"""Tests for the /webhooks/whatsapp controller.

Supabase and the WhatsApp Cloud API are mocked (see conftest.app_module):
whatsapp_webhook_controller's own module-level whatsapp_client/kafka_producer
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


def _inbound_payload(text: str, sender: str = "919876543210", message_id: str = "wamid.1"):
    return _wrap({"from": sender, "id": message_id, "type": "text", "text": {"body": text}})


def _wrap(message: dict):
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [message],
                },
            }],
        }],
    }


@pytest.fixture(autouse=True)
def window_repo(controller, monkeypatch):
    repo = MagicMock()
    monkeypatch.setattr(controller, "whatsapp_repo", repo)
    return repo


def _send(controller):
    return controller.kafka_producer.send_user_conversation_event


def test_receive_message_with_session_fields_acks_and_goes_to_the_summarizer(app_module, controller, monkeypatch):
    monkeypatch.setattr(controller.whatsapp_client, "send_text", MagicMock())
    monkeypatch.setattr(controller.kafka_producer, "send_user_conversation_event", MagicMock(return_value=True))

    client = app_module.app.test_client()
    response = client.post(
        "/webhooks/whatsapp",
        json=_inbound_payload("*Workout Summary*\nSession ID: 12\nDay: 1\n"),
    )

    assert response.status_code == 200
    controller.whatsapp_client.send_text.assert_called_once_with(
        "919876543210", controller.WORKOUT_RECEIVED_MESSAGE
    )
    _send(controller).assert_called_once_with(
        "summarizer", {"session_id": 12, "phone_number": "919876543210"}, key="919876543210"
    )


def test_text_without_session_fields_goes_to_the_router(app_module, controller, monkeypatch):
    monkeypatch.setattr(controller.whatsapp_client, "send_text", MagicMock())
    monkeypatch.setattr(controller.kafka_producer, "send_user_conversation_event", MagicMock(return_value=True))

    client = app_module.app.test_client()
    response = client.post("/webhooks/whatsapp", json=_inbound_payload("knee konjam valikkudhu"))

    assert response.status_code == 200
    controller.whatsapp_client.send_text.assert_not_called()
    _send(controller).assert_called_once_with("router", {
        "phone_number": "919876543210", "whatsapp_message_id": "wamid.1",
        "type": "text", "text": "knee konjam valikkudhu",
    }, key="919876543210")


def test_a_voice_note_goes_to_the_router(app_module, controller, monkeypatch):
    monkeypatch.setattr(controller.kafka_producer, "send_user_conversation_event", MagicMock(return_value=True))

    client = app_module.app.test_client()
    response = client.post("/webhooks/whatsapp", json=_wrap({
        "from": "919876543210", "id": "wamid.2", "type": "audio",
        "audio": {"id": "media-9", "mime_type": "audio/ogg; codecs=opus", "voice": True},
    }))

    assert response.status_code == 200
    _send(controller).assert_called_once_with("router", {
        "phone_number": "919876543210", "whatsapp_message_id": "wamid.2",
        "type": "audio", "media_id": "media-9",
    }, key="919876543210")


def test_receive_message_without_an_id_is_not_published(app_module, controller, monkeypatch):
    monkeypatch.setattr(controller.kafka_producer, "send_user_conversation_event", MagicMock(return_value=True))

    client = app_module.app.test_client()
    response = client.post("/webhooks/whatsapp", json=_wrap(
        {"from": "919876543210", "type": "text", "text": {"body": "hi"}}
    ))

    assert response.status_code == 200
    _send(controller).assert_not_called()


def test_a_failed_router_publish_still_acks(app_module, controller, monkeypatch):
    monkeypatch.setattr(
        controller.kafka_producer, "send_user_conversation_event", MagicMock(side_effect=RuntimeError("down"))
    )

    response = app_module.app.test_client().post("/webhooks/whatsapp", json=_inbound_payload("hi"))

    assert response.status_code == 200


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


def test_every_inbound_message_records_the_reply_window(app_module, controller, monkeypatch, window_repo):
    from datetime import datetime, timezone
    monkeypatch.setattr(controller.kafka_producer, "send_user_conversation_event", MagicMock(return_value=True))

    response = app_module.app.test_client().post("/webhooks/whatsapp", json=_wrap({
        "from": "919876543210", "id": "wamid.3", "timestamp": "1795420000", "type": "image", "image": {"id": "m"},
    }))

    assert response.status_code == 200
    window_repo.record_inbound.assert_called_once_with(
        "919876543210", datetime.fromtimestamp(1795420000, tz=timezone.utc), "wamid.3", "image"
    )
    _send(controller).assert_not_called()  # an image isn't routed, but it still opens the window


def test_a_failed_window_write_does_not_stop_routing(app_module, controller, monkeypatch, window_repo):
    window_repo.record_inbound.side_effect = RuntimeError("db down")
    monkeypatch.setattr(controller.kafka_producer, "send_user_conversation_event", MagicMock(return_value=True))

    response = app_module.app.test_client().post("/webhooks/whatsapp", json=_inbound_payload("hi"))

    assert response.status_code == 200
    _send(controller).assert_called_once()
