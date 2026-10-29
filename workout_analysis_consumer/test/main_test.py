"""Integration test for _process_message.

Only the Claude summary call and the outbound WhatsApp send are mocked
(main.generate_workout_summary, main.whatsapp_client.send_audio), so the
test gets a fixed analysis text without paying for an LLM call, and since
sending a real WhatsApp message has no test recipient. Everything else - the Supabase context fetch,
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
from workout_analysis_consumer.feedback import transcribe_feedback
from workout_analysis_consumer.repository import AnalysisRepository

SESSION_ID = 55
PHONE_NUMBER = "7339284889"

CONSTANT_ANALYSIS_TEXT = (
    "இன்னைக்கு workout semma ஆ முடிச்சிட்டீங்க! எல்லா sets-உம் complete "
    "பண்ணிட்டீங்க, keep it up!"
)


@pytest.mark.integration
@pytest.mark.skipif(not SESSION_ID, reason="set ANALYSIS_IT_SESSION_ID to a test sessions row")
def test_process_message_stores_analysis_and_voice_note(monkeypatch):
    monkeypatch.setattr(
        "workout_analysis_consumer.main.generate_workout_summary",
        MagicMock(return_value=CONSTANT_ANALYSIS_TEXT),
    )

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


@pytest.mark.integration
@pytest.mark.skipif(not SESSION_ID, reason="set ANALYSIS_IT_SESSION_ID to a test sessions row")
def test_process_message_generates_prints_and_stores_real_analysis(monkeypatch):
    """No mocking of the analysis itself: transcribes the session's voice
    feedback with Sarvam, generates the summary with Claude, makes the voice
    note, and upserts session_analysis, printing the transcript and analysis
    (run with -s to see them). Only the outbound side effects are mocked —
    the WhatsApp send and the workout-analysis-complete Kafka event — so
    nothing reaches the client or downstream consumers.
    """
    transcripts = []

    def spy_transcribe_feedback(path):
        transcript = transcribe_feedback(path)
        transcripts.append(transcript)
        return transcript

    monkeypatch.setattr("workout_analysis_consumer.main.transcribe_feedback", spy_transcribe_feedback)
    monkeypatch.setattr("workout_analysis_consumer.main.whatsapp_client.send_audio", MagicMock())
    monkeypatch.setattr("workout_analysis_consumer.main.producer", MagicMock())

    repo = AnalysisRepository()
    _process_message(repo, SESSION_ID, PHONE_NUMBER)

    saved = (
        repo.client.table("session_analysis")
        .select("analysis, audio_url")
        .eq("session_id", SESSION_ID)
        .execute()
        .data
    )

    print(f"\n--- voice feedback transcript (session {SESSION_ID}) ---")
    print(transcripts[0] if transcripts else "(no voice feedback recorded)")
    print(f"--- analysis (session {SESSION_ID}) ---")
    print(saved[0]["analysis"] if saved else "(nothing stored)")
    print(f"--- audio_url ---\n{saved[0]['audio_url'] if saved else None}")

    assert saved
    assert saved[0]["analysis"].strip()
