"""Tests for generate_workout_summary.

Two kinds of coverage here:
- The unit tests below mock the Anthropic client (swap the module-level
  `client` object via monkeypatch, same pattern as main_test.py) so they run
  with no external calls.
- test_generate_workout_summary_against_real_claude (bottom of file) makes a
  real call to claude-sonnet-5-5 - no mocking - same convention as
  backend/tests/kafka_producer/client_test.py does for Kafka.
"""
import json
import os
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from workout_analysis_consumer.prompts import WORKOUT_ANALYSIS_SYSTEM_PROMPT
from workout_analysis_consumer.repository import AnalysisRepository
from workout_analysis_consumer.summarizer import (
    MODEL,
    SummaryRefusedError,
    WorkoutSummary,
    generate_workout_summary,
    spoken_text,
)

# A real sessions row with prescribed exercises (see main_test.py).
SESSION_ID = int(os.environ.get("ANALYSIS_IT_SESSION_ID", "0"))


def _summary(**overrides) -> WorkoutSummary:
    fields = {
        "summary": "Semma workout da!",
        "questions_intro": "Oru sila kelvigal:",
        "questions": [],
        "closing": "Reply pannunga!",
    }
    fields.update(overrides)
    return WorkoutSummary(**fields)


def _mock_client(parsed=None, stop_reason: str = "end_turn", stop_details=None) -> MagicMock:
    mock_client = MagicMock()
    mock_client.beta.messages.parse.return_value = SimpleNamespace(
        parsed_output=parsed,
        stop_reason=stop_reason,
        stop_details=stop_details,
    )
    return mock_client


def _parse_kwargs(mock_client: MagicMock) -> dict:
    mock_client.beta.messages.parse.assert_called_once()
    return mock_client.beta.messages.parse.call_args.kwargs


def test_generate_workout_summary_returns_the_structured_output(monkeypatch):
    summary = _summary()
    monkeypatch.setattr("workout_analysis_consumer.summarizer.client", _mock_client(summary))

    assert generate_workout_summary({"session_id": 1, "day_number": 1}) is summary


def test_generate_workout_summary_sends_system_prompt_and_json_context(monkeypatch):
    mock_client = _mock_client(_summary())
    monkeypatch.setattr("workout_analysis_consumer.summarizer.client", mock_client)

    context = {"session_id": 5, "day_number": 2, "exercises": ["squat", "row"]}
    generate_workout_summary(context)

    kwargs = _parse_kwargs(mock_client)
    assert kwargs["model"] == MODEL == "claude-sonnet-5-5"
    assert kwargs["system"] == WORKOUT_ANALYSIS_SYSTEM_PROMPT
    assert kwargs["output_format"] is WorkoutSummary
    assert kwargs["fallbacks"] == "default"
    assert len(kwargs["messages"]) == 1
    assert kwargs["messages"][0]["role"] == "user"
    assert json.loads(kwargs["messages"][0]["content"]) == context


def test_generate_workout_summary_logs_the_whole_prompt(monkeypatch, caplog):
    monkeypatch.setattr("workout_analysis_consumer.summarizer.client", _mock_client(_summary()))

    with caplog.at_level("INFO", logger="workout_analysis_consumer.summarizer"):
        generate_workout_summary({"session_id": 5, "client_voice_feedback": "இன்னைக்கு romba kashtam"})

    [record] = caplog.records
    assert "session_id=5" in record.getMessage()
    assert WORKOUT_ANALYSIS_SYSTEM_PROMPT in record.getMessage()
    # Tamil is logged (and sent) as-is, not as \\u escapes.
    assert "இன்னைக்கு romba kashtam" in record.getMessage()


def test_generate_workout_summary_serializes_non_json_native_values(monkeypatch):
    """context can carry values json.dumps can't natively serialize (e.g. a
    datetime from a DB row) - the default=str fallback should stringify
    rather than raise.
    """
    mock_client = _mock_client(_summary())
    monkeypatch.setattr("workout_analysis_consumer.summarizer.client", mock_client)

    generate_workout_summary({"logged_at": datetime(2026, 1, 1, 12, 30)})

    assert "2026-01-01" in _parse_kwargs(mock_client)["messages"][0]["content"]


def test_generate_workout_summary_raises_on_refusal(monkeypatch):
    """A refusal shouldn't be saved and sent to the client as if it were a
    summary."""
    mock_client = _mock_client(
        stop_reason="refusal", stop_details=SimpleNamespace(category="general_harms")
    )
    monkeypatch.setattr("workout_analysis_consumer.summarizer.client", mock_client)

    with pytest.raises(SummaryRefusedError, match="general_harms"):
        generate_workout_summary({"session_id": 1})


def test_spoken_text_puts_the_questions_between_summary_and_goodbye():
    summary = _summary()
    questions = [{"text": "Knee eppadi irukku?"}, {"text": "Squat kashtama?"}]

    assert spoken_text(summary, questions) == (
        "Semma workout da! Oru sila kelvigal: Knee eppadi irukku? Squat kashtama? Reply pannunga!"
    )


def test_spoken_text_without_questions_leaves_out_the_intro():
    assert spoken_text(_summary(), []) == "Semma workout da! Reply pannunga!"


@pytest.mark.integration
@pytest.mark.skipif(not SESSION_ID, reason="set ANALYSIS_IT_SESSION_ID to a test sessions row")
def test_generate_workout_summary_against_real_claude():
    """No mocking: builds a real context via AnalysisRepository.fetch_context
    (for the ANALYSIS_IT_SESSION_ID session) and
    calls claude-sonnet-5-5 for real, confirming the actual call site works
    end to end.
    """
    repo = AnalysisRepository()
    context = repo.fetch_context(SESSION_ID)
    assert context is not None

    result = generate_workout_summary(context)

    assert isinstance(result, WorkoutSummary)
    assert result.summary.strip()
    assert len(result.questions) <= 10
