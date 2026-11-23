"""Wiring tests for process_reply: the client's WhatsApp replies to the
clarifying questions, after the router (voice_processor/router.py) found
her open round and transcribed a voice reply. The repository, Claude
(map_reply), TTS and WhatsApp are all mocked."""
from unittest.mock import MagicMock

import pytest

from voice_processor import workout

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


def _reply(repo, text="knee valikkudhu", message_type="text", audio_path=None):
    workout.process_reply(
        repo, repo.find_open_clarification.return_value, PHONE, "wamid.1", message_type, text, audio_path
    )


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
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(workout, name, mock)
    return mocks


def test_an_already_processed_reply_is_skipped(repo, mocks):
    repo.record_reply.return_value = None

    _reply(repo)

    mocks["map_reply"].assert_not_called()


def test_a_partial_answer_is_stored_without_replying(repo, mocks):
    mocks["map_reply"].return_value = {"answers": {"q1": "Knee hurt."}, "notes": [dict(PAIN_NOTE)], "follow_ups": []}

    _reply(repo)

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

    _reply(repo, text="vera onnum illa")

    fields = repo.update_clarification.call_args.args[1]
    assert fields["status"] == "answered"
    assert set(fields["answers"]) == {"q1", "q2"}
    mocks["whatsapp_client"].send_text.assert_called_once_with(PHONE, workout.THANK_YOU_MESSAGE)
    repo.save_clarification.assert_not_called()


def test_follow_ups_open_round_two_and_are_sent_as_a_voice_note(repo, mocks):
    follow_up = {"id": "f1", "text": "Knee-la enga valikkudhu?", "intent": "where",
                 "topic": "joint_pain", "session_exercise_id": 301, "joint": "knee"}
    mocks["map_reply"].return_value = {"answers": {"q1": "Knee hurt."}, "notes": [], "follow_ups": [follow_up]}

    _reply(repo)

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

    _reply(repo)

    assert mocks["map_reply"].call_args.kwargs["follow_ups_allowed"] is False
    # No follow-ups can be asked, so the history isn't fetched.
    repo.fetch_question_history.assert_not_called()
    assert mocks["map_reply"].call_args.kwargs["question_history"] == []


def test_a_voice_reply_keeps_the_routers_audio_and_transcript(repo, mocks):
    _reply(repo, text="voice la sonnadhu", message_type="audio", audio_path="inbound_5.ogg")

    repo.record_reply.assert_called_once_with(70, "wamid.1", "audio", None)
    repo.update_reply.assert_any_call(900, {"audio_path": "inbound_5.ogg", "transcript": "voice la sonnadhu"})
    mocks["whatsapp_client"].download_media.assert_not_called()
    assert mocks["map_reply"].call_args.args[2] == "voice la sonnadhu"


def test_an_empty_reply_is_marked_processed_without_calling_claude(repo, mocks):
    _reply(repo, text="   ")

    mocks["map_reply"].assert_not_called()
    assert "processed_at" in repo.update_reply.call_args.args[1]
