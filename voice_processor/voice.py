import time
from typing import Any, Dict, Optional

from ai_usage import record_tts
from blob_storage_manager import SupabaseBlobStorageManager
from tts import SarvamTTSClient, mp3_to_whatsapp_ogg

_tts_client = SarvamTTSClient()
_blob_storage = SupabaseBlobStorageManager()


def _versioned(url: str) -> str:
    """The URL with a version query string. WhatsApp's Cloud API caches
    media sent by link per URL for several minutes, and a regenerated note
    overwrites the same storage path — so without this a re-shared workout
    would get the previous (cached) voice note. Storage ignores the query."""
    return f"{url}{'&' if '?' in url else '?'}v={time.time_ns()}"


def generate_voice_note_at(text: str, name: str, usage: Optional[Dict[str, Any]] = None) -> str:
    """Turn Tamil/Tanglish text into a WhatsApp-ready voice note stored at
    `name` in the voice-notes bucket, and return its public URL: Sarvam TTS
    -> mp3, transcoded to mono OGG/Opus, uploaded. The URL is versioned per
    generation (see _versioned). `usage` ({"feature", "user_id",
    "session_id"}) records what the TTS call cost (billed per character)."""
    mp3_bytes = _tts_client.convert(text)
    if usage:
        record_tts(text, getattr(_tts_client, "_model", None), **usage)
    ogg_bytes = mp3_to_whatsapp_ogg(mp3_bytes)
    return _versioned(_blob_storage.store(ogg_bytes, name))


def generate_voice_note(
    analysis: str, plan_id: int, day_number: int, suffix: str = "", usage: Optional[Dict[str, Any]] = None
) -> str:
    """A workout's voice note, stored as plan_<id>/day_<n><suffix>.ogg;
    suffix tells apart another note for the same day (e.g. "_followup" for
    follow-up questions). See generate_voice_note_at."""
    return generate_voice_note_at(analysis, f"plan_{plan_id}/day_{day_number}{suffix}.ogg", usage)
