"""Tests for the router (voice_processor/router.py): a WhatsApp message ->
question reply, diet check-in or nothing. The repositories, WhatsApp,
Sarvam, Claude and the diet pipeline are all mocked."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from voice_processor import router, workout
from voice_processor.router_agent import DIET_CHECKIN, OTHER, QUESTION_REPLY

PHONE = "919876543210"
USER = "9876543210"
TODAY = date(2026, 11, 23)
QUESTIONS = [{"id": "q1", "text": "Squat yen kashtam?"}]


def _clarification():
    asked = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    return {"id": 70, "session_id": 48, "user_id": USER, "round": 1, "questions": QUESTIONS, "asked_at": asked}


def _audio(**overrides):
    payload = {"phone_number": PHONE, "whatsapp_message_id": "wamid.1", "type": "audio", "media_id": "media-1"}
    payload.update(overrides)
    return payload


def _text(text, **overrides):
    payload = {"phone_number": PHONE, "whatsapp_message_id": "wamid.1", "type": "text", "text": text}
    payload.update(overrides)
    return payload


@pytest.fixture
def repo():
    repo = MagicMock()
    repo.get_profile_for_routing.return_value = {"user_id": USER, "name": "Priya", "diet_enabled": True}
    repo.get_or_create_inbound.return_value = {"id": 5}
    repo.find_open_clarification.return_value = _clarification()
    repo.recent_meal_reminder.return_value = None
    return repo


@pytest.fixture
def diet_repo():
    diet_repo = MagicMock()
    diet_repo.create_meal_log.return_value = {"id": 600}
    diet_repo.get_meal_log.return_value = {"id": 600, "status": "ready"}
    return diet_repo


@pytest.fixture
def mocks(monkeypatch):
    mocks = SimpleNamespace(
        whatsapp=MagicMock(),
        classify=MagicMock(return_value=SimpleNamespace(label=DIET_CHECKIN, day="today", reason="Food.")),
        transcribe=MagicMock(return_value=("rendu idli saaptaen", "saaras:v4")),
        store=MagicMock(side_effect=lambda audio, name, content_type: name),
        record_stt=MagicMock(),
        process_meal_log=MagicMock(),
        process_reply=MagicMock(),
    )
    mocks.whatsapp.download_media.return_value = (b"ogg", "audio/ogg; codecs=opus")
    monkeypatch.setattr(workout, "whatsapp_client", mocks.whatsapp)
    monkeypatch.setattr(workout, "process_reply", mocks.process_reply)
    monkeypatch.setattr(router.router_agent, "classify_message", mocks.classify)
    monkeypatch.setattr(router, "transcribe_audio_unrecorded", mocks.transcribe)
    monkeypatch.setattr(router, "store_reply_audio", mocks.store)
    monkeypatch.setattr(router, "record_stt", mocks.record_stt)
    monkeypatch.setattr(router, "process_meal_log", mocks.process_meal_log)
    monkeypatch.setattr(router, "today_in", lambda tz=None: TODAY)
    return mocks


def _routed(repo):
    """The route fields written for the message."""
    for call in repo.update_inbound.call_args_list:
        if "route" in call.args[1]:
            return call.args[1]
    return None


def _handled(repo):
    return repo.update_inbound.call_args_list[-1].args[1]


def test_the_client_is_found_by_her_whatsapp_number(repo, diet_repo, mocks):
    router.handle_inbound(repo, diet_repo, _text("rendu idli"))

    repo.get_profile_for_routing.assert_called_once_with(PHONE)


def test_an_international_client_logs_food_on_her_own_day(repo, diet_repo, mocks, monkeypatch):
    repo.get_profile_for_routing.return_value = {
        "user_id": "usr_uk", "name": "Meena", "diet_enabled": True, "timezone": "Europe/London",
    }
    zones = []
    monkeypatch.setattr(router, "today_in", lambda tz=None: zones.append(tz) or TODAY)
    real_now_in = router.now_in
    monkeypatch.setattr(router, "now_in", lambda tz=None: zones.append(tz) or real_now_in(tz))

    router.handle_inbound(repo, diet_repo, _text("porridge", phone_number="447700900123"))

    repo.get_profile_for_routing.assert_called_once_with("447700900123")
    diet_repo.create_meal_log.assert_called_once_with("usr_uk", TODAY, source="whatsapp")
    assert zones == ["Europe/London", "Europe/London"]   # Haiku's "now", then the log's date


def test_an_unknown_sender_is_other_without_downloading(repo, diet_repo, mocks):
    repo.get_profile_for_routing.return_value = None

    router.handle_inbound(repo, diet_repo, _audio())

    assert repo.get_or_create_inbound.call_args.args[0]["user_id"] is None
    assert _routed(repo)["route"] == OTHER
    mocks.whatsapp.download_media.assert_not_called()
    mocks.classify.assert_not_called()


def test_an_already_handled_message_is_skipped(repo, diet_repo, mocks):
    repo.get_or_create_inbound.return_value = {"id": 5, "handled_at": "2026-11-23T10:00:00+00:00"}

    router.handle_inbound(repo, diet_repo, _audio())

    mocks.whatsapp.download_media.assert_not_called()
    repo.update_inbound.assert_not_called()


def test_a_voice_diet_checkin_is_transcribed_once_logged_and_noted(repo, diet_repo, mocks):
    router.handle_inbound(repo, diet_repo, _audio())

    mocks.whatsapp.download_media.assert_called_once_with("media-1")
    mocks.store.assert_called_once_with(b"ogg", "inbound_5.ogg", "audio/ogg")
    mocks.transcribe.assert_called_once_with(b"ogg", "inbound_5.ogg")
    repo.update_inbound.assert_any_call(5, {"audio_path": "inbound_5.ogg", "transcript": "rendu idli saaptaen"})

    payload = mocks.classify.call_args.args[0]
    assert payload["message"] == "rendu idli saaptaen"
    assert payload["allowed_labels"] == [DIET_CHECKIN, QUESTION_REPLY, OTHER]
    assert payload["open_questions"] == QUESTIONS
    assert 29 <= payload["minutes_since_asked"] <= 31

    diet_repo.create_meal_log.assert_called_once_with(USER, TODAY, source="whatsapp")
    diet_repo.update_meal_log.assert_called_once_with(600, {"audio_path": "inbound_5.ogg"})
    _, log_id, transcribe = mocks.process_meal_log.call_args.args
    assert log_id == 600 and transcribe({}) == "rendu idli saaptaen"
    mocks.whatsapp.send_text.assert_called_once_with(PHONE, router.NOTED_MESSAGE)
    mocks.record_stt.assert_called_once_with(b"ogg", "inbound_5.ogg", "saaras:v4", "meal_stt", user_id=USER)
    assert _routed(repo)["route"] == DIET_CHECKIN
    assert _handled(repo)["meal_log_id"] == 600 and "handled_at" in _handled(repo)
    mocks.process_reply.assert_not_called()


def test_food_from_yesterday_is_logged_for_yesterday(repo, diet_repo, mocks):
    mocks.classify.return_value = SimpleNamespace(label=DIET_CHECKIN, day="yesterday", reason="Last night.")

    router.handle_inbound(repo, diet_repo, _text("nethu night dosa"))

    diet_repo.create_meal_log.assert_called_once_with(USER, TODAY - timedelta(days=1), source="whatsapp")
    diet_repo.update_meal_log.assert_not_called()  # a text has no audio


def test_no_food_found_asks_her_to_send_it_again(repo, diet_repo, mocks):
    diet_repo.get_meal_log.return_value = {"id": 600, "status": "failed"}

    router.handle_inbound(repo, diet_repo, _text("saapadu"))

    mocks.whatsapp.send_text.assert_called_once_with(PHONE, router.DIET_RETRY_MESSAGE)


def test_a_reply_goes_to_the_reply_flow_with_the_transcript(repo, diet_repo, mocks):
    mocks.classify.return_value = SimpleNamespace(label=QUESTION_REPLY, day="today", reason="Answers q1.")

    router.handle_inbound(repo, diet_repo, _audio())

    mocks.process_reply.assert_called_once_with(
        repo, repo.find_open_clarification.return_value, PHONE, "wamid.1", "audio",
        "rendu idli saaptaen", "inbound_5.ogg",
    )
    assert mocks.whatsapp.download_media.call_count == 1
    mocks.record_stt.assert_called_once_with(b"ogg", "inbound_5.ogg", "saaras:v4", "reply_stt", user_id=USER)
    assert _handled(repo)["clarification_id"] == 70
    diet_repo.create_meal_log.assert_not_called()


def test_other_does_nothing(repo, diet_repo, mocks):
    mocks.classify.return_value = SimpleNamespace(label=OTHER, day="today", reason="Greeting.")

    router.handle_inbound(repo, diet_repo, _text("good morning"))

    mocks.whatsapp.send_text.assert_not_called()
    mocks.process_reply.assert_not_called()
    diet_repo.create_meal_log.assert_not_called()
    assert _routed(repo)["route"] == OTHER


def test_no_open_questions_and_diet_off_skips_claude(repo, diet_repo, mocks):
    repo.find_open_clarification.return_value = None
    repo.get_profile_for_routing.return_value = {"user_id": USER, "name": "P", "diet_enabled": False}

    router.handle_inbound(repo, diet_repo, _audio())

    mocks.classify.assert_not_called()
    assert _routed(repo)["route"] == OTHER
    mocks.record_stt.assert_called_once_with(b"ogg", "inbound_5.ogg", "saaras:v4", "inbound_stt", user_id=USER)


def test_labels_are_narrowed_to_what_is_possible(repo, diet_repo, mocks):
    repo.find_open_clarification.return_value = None

    router.handle_inbound(repo, diet_repo, _text("rendu idli"))

    payload = mocks.classify.call_args.args[0]
    assert payload["allowed_labels"] == [DIET_CHECKIN, OTHER]
    assert "open_questions" not in payload


def test_diet_off_never_logs_food(repo, diet_repo, mocks):
    repo.get_profile_for_routing.return_value = {"user_id": USER, "name": "P", "diet_enabled": False}
    mocks.classify.return_value = SimpleNamespace(label=QUESTION_REPLY, day="today", reason="Answer.")

    router.handle_inbound(repo, diet_repo, _text("knee fine"))

    assert mocks.classify.call_args.args[0]["allowed_labels"] == [QUESTION_REPLY, OTHER]


def test_a_routing_failure_is_other(repo, diet_repo, mocks):
    mocks.classify.side_effect = RuntimeError("overloaded")

    router.handle_inbound(repo, diet_repo, _text("rendu idli"))

    routed = _routed(repo)
    assert routed["route"] == OTHER and "overloaded" in routed["route_reason"]
    diet_repo.create_meal_log.assert_not_called()


def test_an_empty_voice_note_is_other(repo, diet_repo, mocks):
    mocks.transcribe.return_value = ("  ", "saaras:v4")

    router.handle_inbound(repo, diet_repo, _audio())

    mocks.classify.assert_not_called()
    assert _routed(repo)["route"] == OTHER


def test_a_redelivered_voice_note_reuses_its_transcript(repo, diet_repo, mocks):
    repo.get_or_create_inbound.return_value = {"id": 5, "audio_path": "inbound_5.ogg", "transcript": "rendu idli"}

    router.handle_inbound(repo, diet_repo, _audio())

    mocks.whatsapp.download_media.assert_not_called()
    mocks.transcribe.assert_not_called()
    assert mocks.classify.call_args.args[0]["message"] == "rendu idli"
    mocks.record_stt.assert_not_called()


def test_a_recent_meal_reminder_is_shown_to_the_router(repo, diet_repo, mocks):
    sent = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    repo.recent_meal_reminder.return_value = {"slot": "lunch", "missing_meals": ["lunch"], "sent_at": sent}

    router.handle_inbound(repo, diet_repo, _text("rice sambar"))

    since = repo.recent_meal_reminder.call_args.args[1]
    assert timedelta(hours=2, minutes=59) < datetime.now(timezone.utc) - since < timedelta(hours=3, minutes=1)
    reminder = mocks.classify.call_args.args[0]["meal_reminder"]
    assert reminder["asked_about"] == ["lunch"] and 19 <= reminder["minutes_ago"] <= 21


def test_no_recent_reminder_adds_nothing(repo, diet_repo, mocks):
    router.handle_inbound(repo, diet_repo, _text("rice sambar"))

    assert "meal_reminder" not in mocks.classify.call_args.args[0]


def test_the_reminder_hint_is_left_out_when_diet_is_off(repo, diet_repo, mocks):
    repo.get_profile_for_routing.return_value = {"user_id": USER, "name": "P", "diet_enabled": False}
    repo.recent_meal_reminder.return_value = {"missing_meals": ["lunch"], "sent_at": datetime.now(timezone.utc).isoformat()}

    router.handle_inbound(repo, diet_repo, _text("knee fine"))

    assert "meal_reminder" not in mocks.classify.call_args.args[0]
