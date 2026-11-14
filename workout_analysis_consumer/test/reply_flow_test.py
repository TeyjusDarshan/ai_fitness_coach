"""Wiring tests for _process_reply: the client's WhatsApp replies to the
clarifying questions. The repository, Claude (map_reply), STT, TTS and
WhatsApp are all mocked."""
from unittest.mock import MagicMock

import pytest

from workout_analysis_consumer import main

PHONE = "919876543210"
QUESTIONS = [
    {"id": "q1", "text": "Squat yen kashtam?", "intent": "why", "session_exercise_id": 301, "joint": None},
    {"id": "q2", "text": "Vera edhavadhu?", "intent": "other", "session_exercise_id": None, "joint": None},
]
PAIN_NOTE = {
    "session_exercise_id": 301, "exercise_id": 12, "category": "joint_pain", "difficulty": None,
    "joint_id": 2, "pain_level": "moderate", "urgent": False, "comment": "Knee hurt.",
    "quote": "knee valikkudhu", "question_id": "q1",
}


def _payload(**overrides):
    payload = {"phone_number": PHONE, "whatsapp_message_id": "wamid.1", "type": "text", "text": "knee valikkudhu"}
    payload.update(overrides)
    return payload


def _clarification(round_number=1, answers=None):
    return {
        "id": 70, "session_id": 48, "user_id": "usr_1", "round": round_number,
        "questions": QUESTIONS, "answers": answers or {},
    }


@pytest.fixture
def repo():
    repo = MagicMock()
    repo.find_open_clarification.return_value = _clarification()
    repo.record_reply.return_value = {"id": 900}
    repo.fetch_context.return_value = {
        "session_id": 48, "plan_id": 7, "day_number": 1, "user_id": "usr_1",
        "feedback_audio_path": "x.webm", "exercise_feedback_audio_paths": {},
        "exercises": [{"session_exercise_id": 301, "exercise_id": 12, "name": "Squat"}],
    }
    repo.list_joints.return_value = {"knee": 2}
    repo.list_processed_reply_texts.return_value = ["earlier reply"]
    repo.fetch_question_history.return_value = [{"session_id": 40, "questions": []}]
    return repo


@pytest.fixture
def mocks(monkeypatch):
    mocks = {
        "map_reply": MagicMock(return_value={"answers": {}, "notes": [], "follow_ups": []}),
        "whatsapp_client": MagicMock(),
        "generate_voice_note": MagicMock(return_value="https://audio/followup.ogg"),
        "transcribe_audio": MagicMock(return_value="voice la sonnadhu"),
        "store_reply_audio": MagicMock(side_effect=lambda audio, name, content_type: name),
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(main, name, mock)
    return mocks


def test_a_reply_with_no_open_questions_is_ignored(repo, mocks):
    repo.find_open_clarification.return_value = None

    main._process_reply(repo, _payload())

    repo.record_reply.assert_not_called()
    mocks["map_reply"].assert_not_called()


def test_an_already_processed_reply_is_skipped(repo, mocks):
    repo.record_reply.return_value = None

    main._process_reply(repo, _payload())

    mocks["map_reply"].assert_not_called()


def test_a_partial_answer_is_stored_without_replying(repo, mocks):
    mocks["map_reply"].return_value = {"answers": {"q1": "Knee hurt."}, "notes": [dict(PAIN_NOTE)], "follow_ups": []}

    main._process_reply(repo, _payload())

    args = mocks["map_reply"].call_args
    assert args.args[:3] == (QUESTIONS, ["earlier reply"], "knee valikkudhu")
    assert "feedback_audio_path" not in args.args[3]
    assert args.kwargs["follow_ups_allowed"] is True
    assert args.kwargs["question_history"] == [{"session_id": 40, "questions": []}]
    repo.fetch_question_history.assert_called_once_with("usr_1", 48)
    [stored] = repo.insert_comments.call_args.args[2]
    assert (stored["source"], stored["clarification_reply_id"], stored["question_id"]) == (
        "clarification_reply", 900, "q1"
    )
    repo.apply_joint_pain.assert_called_once_with("usr_1", {2: "moderate"})
    repo.update_clarification.assert_called_once_with(
        70, {"answers": {"q1": {"summary": "Knee hurt.", "reply_id": 900}}}
    )
    mocks["whatsapp_client"].send_text.assert_not_called()
    mocks["whatsapp_client"].send_audio.assert_not_called()
    assert "processed_at" in repo.update_reply.call_args.args[1]


def test_answering_everything_closes_the_round_and_thanks_her(repo, mocks):
    repo.find_open_clarification.return_value = _clarification(
        answers={"q1": {"summary": "Knee hurt.", "reply_id": 899}}
    )
    mocks["map_reply"].return_value = {"answers": {"q2": "Nothing else."}, "notes": [], "follow_ups": []}

    main._process_reply(repo, _payload(text="vera onnum illa"))

    fields = repo.update_clarification.call_args.args[1]
    assert fields["status"] == "answered"
    assert set(fields["answers"]) == {"q1", "q2"}
    mocks["whatsapp_client"].send_text.assert_called_once_with(PHONE, main.THANK_YOU_MESSAGE)
    repo.save_clarification.assert_not_called()


def test_follow_ups_open_round_two_and_are_sent_as_a_voice_note(repo, mocks):
    follow_up = {"id": "f1", "text": "Knee-la enga valikkudhu?", "intent": "where",
                 "topic": "joint_pain", "session_exercise_id": 301, "joint": "knee"}
    mocks["map_reply"].return_value = {"answers": {"q1": "Knee hurt."}, "notes": [], "follow_ups": [follow_up]}

    main._process_reply(repo, _payload())

    fields = repo.update_clarification.call_args.args[1]
    assert fields["status"] == "superseded"  # q2 never answered
    repo.save_clarification.assert_called_once_with(48, "usr_1", PHONE, 2, [follow_up])
    text = mocks["generate_voice_note"].call_args.args[0]
    assert "Knee-la enga valikkudhu?" in text
    assert mocks["generate_voice_note"].call_args.kwargs == {
        "suffix": "_followup", "usage": {"feature": "follow_up_tts", "user_id": "usr_1", "session_id": 48},
    }
    mocks["whatsapp_client"].send_audio.assert_called_once_with(PHONE, "https://audio/followup.ogg")


def test_round_two_allows_no_more_follow_ups(repo, mocks):
    repo.find_open_clarification.return_value = _clarification(round_number=2)

    main._process_reply(repo, _payload())

    assert mocks["map_reply"].call_args.kwargs["follow_ups_allowed"] is False
    # No follow-ups can be asked, so the history isn't fetched.
    repo.fetch_question_history.assert_not_called()
    assert mocks["map_reply"].call_args.kwargs["question_history"] == []


def test_a_voice_reply_is_downloaded_stored_and_transcribed(repo, mocks):
    mocks["whatsapp_client"].download_media.return_value = (b"ogg-bytes", "audio/ogg; codecs=opus")

    main._process_reply(repo, _payload(type="audio", text=None, media_id="media-1"))

    mocks["whatsapp_client"].download_media.assert_called_once_with("media-1")
    mocks["store_reply_audio"].assert_called_once_with(b"ogg-bytes", "session_48_reply_900.ogg", "audio/ogg")
    mocks["transcribe_audio"].assert_called_once_with(
        b"ogg-bytes", "session_48_reply_900.ogg", {"feature": "reply_stt", "user_id": "usr_1", "session_id": 48}
    )
    repo.update_reply.assert_any_call(
        900, {"audio_path": "session_48_reply_900.ogg", "transcript": "voice la sonnadhu"}
    )
    assert mocks["map_reply"].call_args.args[2] == "voice la sonnadhu"


def test_an_empty_reply_is_marked_processed_without_calling_claude(repo, mocks):
    main._process_reply(repo, _payload(text="   "))

    mocks["map_reply"].assert_not_called()
    assert "processed_at" in repo.update_reply.call_args.args[1]
