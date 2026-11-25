"""generate_voice_note returns a fresh URL each time, so WhatsApp (which
caches media sent by link per URL) never replays an older note; workout
notes are spoken by ElevenLabs (falling back to Sarvam), everything else by
Sarvam."""
from unittest.mock import MagicMock

import pytest

from voice_processor import voice

URL = "https://x.supabase.co/storage/v1/object/public/voice-notes/plan_76/day_5.ogg"
USAGE = {"feature": "summary_tts", "user_id": "usr_1", "session_id": 9}


def _client(provider, model, audio=b"mp3", error=None):
    convert = MagicMock(return_value=audio, side_effect=error)
    return MagicMock(convert=convert, provider=provider, _model=model)


@pytest.fixture
def mocks(monkeypatch):
    mocks = {
        "sarvam": _client("sarvam", "bulbul:v3", b"sarvam-mp3"),
        "elevenlabs": _client("elevenlabs", "eleven_v4_turbo", b"eleven-mp3"),
        "storage": MagicMock(store=MagicMock(return_value=URL)),
        "ogg": MagicMock(return_value=b"ogg"),
        "record_tts": MagicMock(),
    }
    monkeypatch.setattr(voice, "_sarvam_client", mocks["sarvam"])
    monkeypatch.setattr(voice, "_elevenlabs_client", mocks["elevenlabs"])
    monkeypatch.setattr(voice, "_blob_storage", mocks["storage"])
    monkeypatch.setattr(voice, "mp3_to_whatsapp_ogg", mocks["ogg"])
    monkeypatch.setattr(voice, "record_tts", mocks["record_tts"])
    return mocks


def test_each_voice_note_gets_a_unique_versioned_url(mocks):
    first = voice.generate_voice_note("text", 76, 5)
    second = voice.generate_voice_note("text", 76, 5)

    mocks["storage"].store.assert_called_with(b"ogg", "plan_76/day_5.ogg")
    assert first.startswith(URL + "?v=") and second.startswith(URL + "?v=")
    assert first != second


def test_workout_notes_are_spoken_by_elevenlabs_and_recorded_against_it(mocks):
    voice.generate_voice_note("Hi ma!", 76, 5, usage=USAGE)

    mocks["elevenlabs"].convert.assert_called_once_with("Hi ma!")
    mocks["sarvam"].convert.assert_not_called()
    mocks["ogg"].assert_called_once_with(b"eleven-mp3")
    mocks["record_tts"].assert_called_once_with("Hi ma!", "eleven_v4_turbo", provider="elevenlabs", **USAGE)


def test_an_elevenlabs_failure_falls_back_to_sarvam(mocks):
    mocks["elevenlabs"].convert.side_effect = RuntimeError("quota exceeded")

    url = voice.generate_voice_note("Hi ma!", 76, 5, usage=USAGE)

    assert url.startswith(URL)
    mocks["ogg"].assert_called_once_with(b"sarvam-mp3")
    mocks["record_tts"].assert_called_once_with("Hi ma!", "bulbul:v3", provider="sarvam", **USAGE)


def test_missing_elevenlabs_config_falls_back_to_sarvam(mocks, monkeypatch):
    monkeypatch.setattr(voice, "_elevenlabs_client", None)
    monkeypatch.setattr(voice, "ElevenLabsTTSClient", MagicMock(side_effect=KeyError("ELEVENLABS_API_KEY")))

    voice.generate_voice_note("Hi ma!", 76, 5)

    mocks["ogg"].assert_called_once_with(b"sarvam-mp3")


def test_other_voice_notes_stay_on_sarvam(mocks):
    voice.generate_voice_note_at("Saapteengala?", "reminders/usr_1/x.ogg", usage=USAGE)

    mocks["elevenlabs"].convert.assert_not_called()
    mocks["ogg"].assert_called_once_with(b"sarvam-mp3")


def test_a_url_that_already_has_a_query_gets_another_parameter():
    assert voice._versioned(URL + "?token=a").startswith(URL + "?token=a&v=")
