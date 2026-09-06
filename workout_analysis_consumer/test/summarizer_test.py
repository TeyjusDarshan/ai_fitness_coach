"""Tests for generate_workout_summary.

Two kinds of coverage here:
- The unit tests below mock the LLM (swap the module-level `llm` object via
  monkeypatch, same pattern as main_test.py) so they run with no external
  calls.
- test_generate_workout_summary_against_real_gemini (bottom of file) makes a
  real call to gemini-3.8-flash - no mocking - same convention as
  backend/tests/kafka_producer/client_test.py does for Kafka.
"""
import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from workout_analysis_consumer.prompts import WORKOUT_ANALYSIS_SYSTEM_PROMPT
from workout_analysis_consumer.repository import AnalysisRepository
from workout_analysis_consumer.summarizer import generate_workout_summary

SESSION_ID = 37
DAY_NUMBER = 5


def _mock_llm(content: str) -> MagicMock:
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=content)
    return mock_llm


def test_generate_workout_summary_returns_stripped_llm_content(monkeypatch):
    mock_llm = _mock_llm("  Semma workout da! Keep it up.  \n")
    monkeypatch.setattr("workout_analysis_consumer.summarizer.llm", mock_llm)

    result = generate_workout_summary({"session_id": 1, "day_number": 1})

    assert result == "Semma workout da! Keep it up."


def test_generate_workout_summary_sends_system_prompt_and_json_context(monkeypatch):
    mock_llm = _mock_llm("analysis text")
    monkeypatch.setattr("workout_analysis_consumer.summarizer.llm", mock_llm)

    context = {"session_id": 5, "day_number": 2, "exercises": ["squat", "row"]}
    generate_workout_summary(context)

    mock_llm.invoke.assert_called_once()
    messages = mock_llm.invoke.call_args.args[0]
    assert len(messages) == 2

    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == WORKOUT_ANALYSIS_SYSTEM_PROMPT

    assert isinstance(messages[1], HumanMessage)
    assert json.loads(messages[1].content) == context


def test_generate_workout_summary_serializes_non_json_native_values(monkeypatch):
    """context can carry values json.dumps can't natively serialize (e.g. a
    datetime from a DB row) - the default=str fallback should stringify
    rather than raise.
    """
    mock_llm = _mock_llm("analysis text")
    monkeypatch.setattr("workout_analysis_consumer.summarizer.llm", mock_llm)

    context = {"logged_at": datetime(2026, 1, 1, 12, 30)}
    generate_workout_summary(context)

    messages = mock_llm.invoke.call_args.args[0]
    assert "2026-01-01" in messages[1].content


@pytest.mark.integration
def test_generate_workout_summary_against_real_gemini():
    """No mocking: builds a real context via AnalysisRepository.fetch_context
    (session_id=37, day_number=5, which has real prescribed exercises) and
    calls gemini-3.8-flash for real, confirming the actual call site works
    end to end post-migration.
    """
    repo = AnalysisRepository()
    context = repo.fetch_context(SESSION_ID, DAY_NUMBER)
    assert context is not None

    result = generate_workout_summary(context)

    assert isinstance(result, str)
    assert result.strip()
