"""Integration test for _process_message.

Only the Gemini LLM call is mocked (summarizer.llm.invoke), since it's
currently unreliable to call for real in a test run (tier/rate-limit issues
on the free plan - see summarizer.py). Everything downstream of it - the
Supabase context fetch, Sarvam TTS, the mp3->ogg conversion, the Supabase
Storage upload, and the session_day_analysis upsert - runs for real, same as
backend/tests/kafka_producer/client_test.py does for Kafka.
"""
from unittest.mock import MagicMock

import pytest

from workout_analysis_consumer.main import _process_message
from workout_analysis_consumer.repository import AnalysisRepository

SESSION_ID = 37
DAY_NUMBER = 5

CONSTANT_ANALYSIS_TEXT = (
    "இன்னைக்கு workout semma ஆ முடிச்சிட்டீங்க! எல்லா sets-உம் complete "
    "பண்ணிட்டீங்க, keep it up!"
)


@pytest.mark.integration
def test_process_message_stores_analysis_and_voice_note(monkeypatch):
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=CONSTANT_ANALYSIS_TEXT)
    monkeypatch.setattr("workout_analysis_consumer.summarizer.llm", mock_llm)

    repo = AnalysisRepository()
    _process_message(repo, SESSION_ID, DAY_NUMBER)

    saved = (
        repo.client.table("session_day_analysis")
        .select("analysis, audio_url")
        .eq("session_id", SESSION_ID)
        .eq("day_number", DAY_NUMBER)
        .execute()
        .data
    )

    assert saved
    assert saved[0]["analysis"] == CONSTANT_ANALYSIS_TEXT
    assert saved[0]["audio_url"]
