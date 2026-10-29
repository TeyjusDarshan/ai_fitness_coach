"""Tests for transcribing the client's voice feedback into the analysis.

The _process_message tests mock everything outside the consumer (the
transcription, the Claude summary, the voice note, WhatsApp and Kafka), so
they only check the wiring. test_transcribe_feedback_against_real_sarvam
(bottom of file) downloads a real recording and calls Sarvam for real, same
convention as main_test.py.
"""
import os
from unittest.mock import MagicMock

import pytest

from workout_analysis_consumer import main
from workout_analysis_consumer.feedback import transcribe_feedback
from workout_analysis_consumer.repository import AnalysisRepository

SESSION_ID = int(os.environ.get("ANALYSIS_IT_SESSION_ID", "0"))


@pytest.fixture
def mocks(monkeypatch):
    mocks = {
        "transcribe_feedback": MagicMock(return_value="squats romba kashtama irundhuchu"),
        "generate_workout_summary": MagicMock(return_value="analysis text"),
        "generate_voice_note": MagicMock(return_value=None),
        "producer": MagicMock(),
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(main, name, mock)
    return mocks


def _repo(feedback_audio_path):
    repo = MagicMock()
    repo.fetch_context.return_value = {
        "session_id": 48, "plan_id": 7, "day_number": 1, "user_id": "usr_1",
        "feedback_audio_path": feedback_audio_path, "exercises": [],
    }
    return repo


def _summary_context(mocks):
    mocks["generate_workout_summary"].assert_called_once()
    return mocks["generate_workout_summary"].call_args.args[0]


def test_voice_feedback_transcript_is_sent_to_claude_without_the_storage_path(mocks):
    main._process_message(_repo("session_48.webm"), 48, "919876543210")

    mocks["transcribe_feedback"].assert_called_once_with("session_48.webm")
    context = _summary_context(mocks)
    assert context["client_voice_feedback"] == "squats romba kashtama irundhuchu"
    assert "feedback_audio_path" not in context


def test_a_failed_transcription_still_generates_the_analysis(mocks):
    mocks["transcribe_feedback"].side_effect = RuntimeError("sarvam down")
    repo = _repo("session_48.webm")

    main._process_message(repo, 48, "919876543210")

    assert "client_voice_feedback" not in _summary_context(mocks)
    repo.save_analysis.assert_called_once_with(48, "analysis text", None)


@pytest.mark.parametrize("transcript", ["", None])
def test_an_empty_transcript_is_left_out(mocks, transcript):
    mocks["transcribe_feedback"].return_value = transcript

    main._process_message(_repo("session_48.webm"), 48, "919876543210")

    assert "client_voice_feedback" not in _summary_context(mocks)


def test_no_recording_skips_transcription(mocks):
    main._process_message(_repo(None), 48, "919876543210")

    mocks["transcribe_feedback"].assert_not_called()
    context = _summary_context(mocks)
    assert "client_voice_feedback" not in context
    assert "feedback_audio_path" not in context


@pytest.mark.integration
@pytest.mark.skipif(not SESSION_ID, reason="set ANALYSIS_IT_SESSION_ID to a test sessions row")
def test_transcribe_feedback_against_real_sarvam():
    """No mocking: downloads the ANALYSIS_IT_SESSION_ID session's recording
    from the voice-feedback bucket and runs a real Sarvam batch job on it."""
    context = AnalysisRepository().fetch_context(SESSION_ID)
    assert context is not None
    if not context["feedback_audio_path"]:
        pytest.skip("this session has no recorded voice feedback")

    transcript = transcribe_feedback(context["feedback_audio_path"])

    assert transcript.strip()
