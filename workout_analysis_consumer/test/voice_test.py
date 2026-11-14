"""generate_voice_note returns a fresh URL each time, so WhatsApp (which
caches media sent by link per URL) never replays an older note."""
from unittest.mock import MagicMock

from workout_analysis_consumer import voice

URL = "https://x.supabase.co/storage/v1/object/public/voice-notes/plan_76/day_5.ogg"


def test_each_voice_note_gets_a_unique_versioned_url(monkeypatch):
    monkeypatch.setattr(voice, "_tts_client", MagicMock(convert=MagicMock(return_value=b"mp3")))
    monkeypatch.setattr(voice, "mp3_to_whatsapp_ogg", MagicMock(return_value=b"ogg"))
    storage = MagicMock(store=MagicMock(return_value=URL))
    monkeypatch.setattr(voice, "_blob_storage", storage)

    first = voice.generate_voice_note("text", 76, 5)
    second = voice.generate_voice_note("text", 76, 5)

    storage.store.assert_called_with(b"ogg", "plan_76/day_5.ogg")
    assert first.startswith(URL + "?v=") and second.startswith(URL + "?v=")
    assert first != second


def test_a_url_that_already_has_a_query_gets_another_parameter():
    assert voice._versioned(URL + "?token=a").startswith(URL + "?token=a&v=")
