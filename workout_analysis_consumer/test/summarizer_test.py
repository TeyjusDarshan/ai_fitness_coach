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
    generate_workout_summary,
)

# A real sessions row with prescribed exercises (see main_test.py).
SESSION_ID = int(os.environ.get("ANALYSIS_IT_SESSION_ID", "0"))


def _mock_client(*texts: str, stop_reason: str = "end_turn", stop_details=None) -> MagicMock:
    mock_client = MagicMock()
    mock_client.beta.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking="")]
        + [SimpleNamespace(type="text", text=text) for text in texts],
        stop_reason=stop_reason,
        stop_details=stop_details,
    )
    return mock_client


def _create_kwargs(mock_client: MagicMock) -> dict:
    mock_client.beta.messages.create.assert_called_once()
    return mock_client.beta.messages.create.call_args.kwargs


def test_generate_workout_summary_returns_stripped_text_blocks(monkeypatch):
    mock_client = _mock_client("  Semma workout da! ", "Keep it up.  \n")
    monkeypatch.setattr("workout_analysis_consumer.summarizer.client", mock_client)

    result = generate_workout_summary({"session_id": 1, "day_number": 1})

    assert result == "Semma workout da! Keep it up."


def test_generate_workout_summary_sends_system_prompt_and_json_context(monkeypatch):
    mock_client = _mock_client("analysis text")
    monkeypatch.setattr("workout_analysis_consumer.summarizer.client", mock_client)

    context = {"session_id": 5, "day_number": 2, "exercises": ["squat", "row"]}
    generate_workout_summary(context)

    kwargs = _create_kwargs(mock_client)
    assert kwargs["model"] == MODEL == "claude-sonnet-5-5"
    assert kwargs["system"] == WORKOUT_ANALYSIS_SYSTEM_PROMPT
    assert kwargs["fallbacks"] == "default"
    assert len(kwargs["messages"]) == 1
    assert kwargs["messages"][0]["role"] == "user"
    assert json.loads(kwargs["messages"][0]["content"]) == context


def test_generate_workout_summary_logs_the_whole_prompt(monkeypatch, caplog):
    monkeypatch.setattr("workout_analysis_consumer.summarizer.client", _mock_client("analysis text"))

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
    mock_client = _mock_client("analysis text")
    monkeypatch.setattr("workout_analysis_consumer.summarizer.client", mock_client)

    context = {"logged_at": datetime(2026, 1, 1, 12, 30)}
    generate_workout_summary(context)

    assert "2026-01-01" in _create_kwargs(mock_client)["messages"][0]["content"]


def test_generate_workout_summary_raises_on_refusal(monkeypatch):
    """A refusal shouldn't be saved and sent to the client as if it were a
    summary."""
    mock_client = _mock_client(
        stop_reason="refusal", stop_details=SimpleNamespace(category="general_harms")
    )
    monkeypatch.setattr("workout_analysis_consumer.summarizer.client", mock_client)

    with pytest.raises(SummaryRefusedError, match="general_harms"):
        generate_workout_summary({"session_id": 1})


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

    assert isinstance(result, str)
    assert result.strip()
