"""diet/transcription.py: the fast/batch choice, and recording the cost
either straight away (the PWA) or by the caller (the WhatsApp router)."""
from unittest.mock import MagicMock

from diet import transcription


def _clients(monkeypatch, seconds):
    fast, batch = MagicMock(_model="saaras:v4"), MagicMock(_model="saaras:v4-batch")
    fast.transcribe.return_value, batch.transcribe.return_value = "fast text", "batch text"
    monkeypatch.setattr(transcription, "audio_seconds", lambda audio: seconds)
    monkeypatch.setattr(transcription, "SarvamRestSTTClient", lambda: fast)
    monkeypatch.setattr(transcription, "SarvamBatchSTTClient", lambda: batch)
    record = MagicMock()
    monkeypatch.setattr(transcription, "record_stt", record)
    return fast, batch, record


def test_unrecorded_returns_the_model_and_records_nothing(monkeypatch):
    _, batch, record = _clients(monkeypatch, seconds=40)

    assert transcription.transcribe_audio_unrecorded(b"a", "x.ogg") == ("batch text", "saaras:v4-batch")
    record.assert_not_called()


def test_a_short_recording_uses_the_fast_endpoint_and_is_recorded_as_meal_stt(monkeypatch):
    fast, batch, record = _clients(monkeypatch, seconds=10)

    assert transcription.transcribe_audio(b"a", "x.ogg", "usr_1") == "fast text"
    batch.transcribe.assert_not_called()
    record.assert_called_once_with(b"a", "x.ogg", "saaras:v4", "meal_stt", user_id="usr_1")
