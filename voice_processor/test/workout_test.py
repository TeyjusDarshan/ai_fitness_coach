"""Integration test for _process_message.

Only the Claude summary call and the outbound WhatsApp send are mocked
(workout.generate_workout_summary, workout.whatsapp_client.send_audio), so the
test gets a fixed analysis text without paying for an LLM call, and since
sending a real WhatsApp message has no test recipient. Everything else - the Supabase context fetch,
the voice note (ElevenLabs, falling back to Sarvam), the mp3->ogg conversion, the Supabase Storage upload, and the
session_analysis upsert - runs for real, same as
backend/tests/kafka_producer/client_test.py does for Kafka. To see a real
Claude summary and voice note without writing anything, use
`python -m voice_processor.dry_run --session-id N --voice-out x.mp3`.

It writes a real session_analysis row, so it only runs against the sessions
row named by ANALYSIS_IT_SESSION_ID (one with logged exercises, ideally a
throwaway test user's) and is skipped when that isn't set.
"""
import os
from unittest.mock import MagicMock

import pytest

from voice_processor.workout import _process_message
from voice_processor.repository import AnalysisRepository
from voice_processor.summarizer import WorkoutSummary

# Opt-in: a real sessions row (ideally a throwaway test user's). Unset, the
# test is skipped, so a normal test run writes nothing and spends nothing.
SESSION_ID = int(os.environ.get("ANALYSIS_IT_SESSION_ID", "0"))
PHONE_NUMBER = "7339284889"

CONSTANT_ANALYSIS_TEXT = (
    "இன்னைக்கு workout semma ஆ முடிச்சிட்டீங்க! எல்லா sets-உம் complete "
    "பண்ணிட்டீங்க, keep it up!"
)


@pytest.mark.integration
@pytest.mark.skipif(not SESSION_ID, reason="set ANALYSIS_IT_SESSION_ID to a test sessions row")
def test_process_message_stores_analysis_and_voice_note(monkeypatch):
    monkeypatch.setattr(
        "voice_processor.workout.generate_workout_summary",
        MagicMock(return_value=WorkoutSummary(
            summary=CONSTANT_ANALYSIS_TEXT, questions=[],
        )),
    )

    mock_send_audio = MagicMock()
    monkeypatch.setattr("voice_processor.workout.whatsapp_client.send_audio", mock_send_audio)

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
