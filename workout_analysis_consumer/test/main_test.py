"""Integration test for _process_message.

Only the Gemini LLM call and the outbound WhatsApp send are mocked
(summarizer.llm.invoke, main.whatsapp_client.send_audio), since it's
currently unreliable to call the LLM for real in a test run (tier/rate-limit
issues on the free plan - see summarizer.py) and sending a real WhatsApp
message has no test recipient. Everything else - the Supabase context fetch,
Sarvam TTS, the mp3->ogg conversion, the Supabase Storage upload, and the
session_analysis upsert - runs for real, same as
backend/tests/kafka_producer/client_test.py does for Kafka.

It writes a real session_analysis row, so it only runs against the sessions
row named by ANALYSIS_IT_SESSION_ID (one with logged exercises, ideally a
throwaway test user's) and is skipped when that isn't set.
"""
import os
from unittest.mock import MagicMock

import pytest

from workout_analysis_consumer.main import _process_message
from workout_analysis_consumer.repository import AnalysisRepository

SESSION_ID = int(os.environ.get("ANALYSIS_IT_SESSION_ID", "0"))
PHONE_NUMBER = "919876543210"

CONSTANT_ANALYSIS_TEXT = (
    "இன்னைக்கு workout semma ஆ முடிச்சிட்டீங்க! எல்லா sets-உம் complete "
    "பண்ணிட்டீங்க, keep it up!"
)


@pytest.mark.integration
@pytest.mark.skipif(not SESSION_ID, reason="set ANALYSIS_IT_SESSION_ID to a test sessions row")
def test_process_message_stores_analysis_and_voice_note(monkeypatch):
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=CONSTANT_ANALYSIS_TEXT)
    monkeypatch.setattr("workout_analysis_consumer.summarizer.llm", mock_llm)

    mock_send_audio = MagicMock()
    monkeypatch.setattr("workout_analysis_consumer.main.whatsapp_client.send_audio", mock_send_audio)

    repo = AnalysisRepository()
    _process_message(repo, SESSION_ID, PHONE_NUMBER)

    saved = (
        repo.client.table("session_analysis")
        .select("analysis, audio_url")
        .eq("session_id", SESSION_ID)
        .execute()
        .data
    )

    assert saved
    assert saved[0]["analysis"] == CONSTANT_ANALYSIS_TEXT
    assert saved[0]["audio_url"]
    mock_send_audio.assert_called_once_with(PHONE_NUMBER, saved[0]["audio_url"])
