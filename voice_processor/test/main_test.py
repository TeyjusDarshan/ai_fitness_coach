"""Tests for the voice processor's routing (voice_processor/main.py): each
topic's messages go to that topic's handler, and a failing message is
skipped rather than stopping the loop."""
import json
from unittest.mock import MagicMock

from voice_processor import main
from voice_processor.consumer import FEEDBACK_REPLY_TOPIC, MEAL_LOG_TOPIC, WORKOUT_COMPLETE_TOPIC


def test_every_topic_has_its_own_handler(monkeypatch):
    calls = MagicMock()
    monkeypatch.setattr(main.workout, "handle_workout_complete", calls.workout_complete)
    monkeypatch.setattr(main.workout, "handle_feedback_reply", calls.feedback_reply)
    monkeypatch.setattr(main, "process_meal_log", calls.meal_log)
    workout_repo, diet_repo = MagicMock(), MagicMock()
    handlers = main.build_handlers(workout_repo, diet_repo)

    main.handle_message(handlers, WORKOUT_COMPLETE_TOPIC, json.dumps({"session_id": 7, "phone_number": "91"}))
    main.handle_message(handlers, FEEDBACK_REPLY_TOPIC, json.dumps({"phone_number": "91", "text": "ok"}))
    main.handle_message(handlers, MEAL_LOG_TOPIC, json.dumps({"meal_log_id": 12}))

    calls.workout_complete.assert_called_once_with(workout_repo, {"session_id": 7, "phone_number": "91"})
    calls.feedback_reply.assert_called_once_with(workout_repo, {"phone_number": "91", "text": "ok"})
    calls.meal_log.assert_called_once_with(diet_repo, 12, main.transcribe_meal_log)
    assert set(handlers) == {WORKOUT_COMPLETE_TOPIC, FEEDBACK_REPLY_TOPIC, MEAL_LOG_TOPIC}


def test_a_bad_message_or_unknown_topic_is_skipped():
    failing = MagicMock(side_effect=RuntimeError("boom"))
    handlers = {"t": failing}

    main.handle_message(handlers, "t", b'{"meal_log_id": 1}')   # handler raises
    main.handle_message(handlers, "t", b"not json")             # never reaches it
    main.handle_message(handlers, "other", b"{}")               # no handler

    failing.assert_called_once_with({"meal_log_id": 1})
