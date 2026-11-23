"""Tests for the voice processor's dispatch (voice_processor/main.py and
processors.py): each user-conversation event goes to the processor its
`target` names, and a failing event is skipped rather than stopping the loop."""
import json
from unittest.mock import MagicMock

from voice_processor import main, processors
from voice_processor.consumer import TARGET_DIET, TARGET_ROUTER, TARGET_SUMMARIZER


def test_every_target_has_its_own_processor(monkeypatch):
    calls = MagicMock()
    monkeypatch.setattr(processors.workout, "handle_workout_complete", calls.summarizer)
    monkeypatch.setattr(processors.router, "handle_inbound", calls.router)
    monkeypatch.setattr(processors, "process_meal_log", calls.diet)
    workout_repo, diet_repo = MagicMock(), MagicMock()
    registry = processors.build_processors(workout_repo, diet_repo)

    summarizer = {"target": TARGET_SUMMARIZER, "session_id": 7, "phone_number": "91"}
    routed = {"target": TARGET_ROUTER, "phone_number": "91", "whatsapp_message_id": "w", "type": "text", "text": "ok"}
    main.handle_message(registry, json.dumps(summarizer))
    main.handle_message(registry, json.dumps(routed))
    main.handle_message(registry, json.dumps({"target": TARGET_DIET, "meal_log_id": 12}))

    calls.summarizer.assert_called_once_with(workout_repo, summarizer)
    calls.router.assert_called_once_with(workout_repo, diet_repo, routed)
    calls.diet.assert_called_once_with(diet_repo, 12, processors.transcribe_meal_log)
    assert set(registry) == {TARGET_SUMMARIZER, TARGET_ROUTER, TARGET_DIET}


def test_a_bad_event_or_unknown_target_is_skipped():
    failing = MagicMock()
    failing.handle.side_effect = RuntimeError("boom")
    registry = {"t": failing}

    main.handle_message(registry, b'{"target": "t", "meal_log_id": 1}')  # processor raises
    main.handle_message(registry, b"not json")                         # never reaches it
    main.handle_message(registry, b'{"target": "other"}')               # no processor
    main.handle_message(registry, b'{"meal_log_id": 1}')                # no target

    failing.handle.assert_called_once_with({"target": "t", "meal_log_id": 1})
