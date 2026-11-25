import logging
import time
from typing import Any, Dict, Optional

from ai_usage import record_tts
from blob_storage_manager import SupabaseBlobStorageManager
from tts import ElevenLabsTTSClient, SarvamTTSClient, TTSClient, mp3_to_whatsapp_ogg

logger = logging.getLogger(__name__)

# Sarvam is the fallback for the workout notes (meal feedback and meal
# reminders are plain texts now, with no voice note). ElevenLabs (the coach's cloned voice) speaks the
# workout summary and follow-up questions; it's created on first use, so a
# missing ELEVENLABS_* setting only sends those notes to the fallback.
_sarvam_client: TTSClient = SarvamTTSClient()
_elevenlabs_client: Optional[TTSClient] = None
_blob_storage = SupabaseBlobStorageManager()


def _elevenlabs() -> TTSClient:
    global _elevenlabs_client
    if _elevenlabs_client is None:
        _elevenlabs_client = ElevenLabsTTSClient()
    return _elevenlabs_client


def _versioned(url: str) -> str:
    """The URL with a version query string. WhatsApp's Cloud API caches
    media sent by link per URL for several minutes, and a regenerated note
    overwrites the same storage path — so without this a re-shared workout
    would get the previous (cached) voice note. Storage ignores the query."""
    return f"{url}{'&' if '?' in url else '?'}v={time.time_ns()}"


def _speak(text: str, usage: Optional[Dict[str, Any]], prefer_elevenlabs: bool) -> bytes:
    """mp3 for `text`, recording the call's cost against whichever provider
    actually spoke it. With prefer_elevenlabs, any ElevenLabs failure
    (missing config, out of credits, network) is logged and Sarvam speaks
    it instead, so the client still gets a voice note."""
    if prefer_elevenlabs:
        try:
            client = _elevenlabs()
            mp3_bytes = client.convert(text)
        except Exception:
            logger.exception("ElevenLabs TTS failed; falling back to Sarvam")
        else:
            if usage:
                record_tts(text, client._model, provider=client.provider, **usage)
            return mp3_bytes
    mp3_bytes = _sarvam_client.convert(text)
    if usage:
        record_tts(text, _sarvam_client._model, provider=_sarvam_client.provider, **usage)
    return mp3_bytes


def generate_voice_note_at(
    text: str, name: str, usage: Optional[Dict[str, Any]] = None, prefer_elevenlabs: bool = False
) -> str:
    """Turn Tamil/Tanglish text into a WhatsApp-ready voice note stored at
    `name` in the voice-notes bucket, and return its public URL: TTS -> mp3,
    transcoded to mono OGG/Opus, uploaded. Sarvam speaks it unless
    prefer_elevenlabs (see _speak). The URL is versioned per generation (see
    _versioned). `usage` ({"feature", "user_id", "session_id"}) records what
    the TTS call cost (billed per character)."""
    mp3_bytes = _speak(text, usage, prefer_elevenlabs)
    ogg_bytes = mp3_to_whatsapp_ogg(mp3_bytes)
    return _versioned(_blob_storage.store(ogg_bytes, name))


def generate_voice_note(
    analysis: str, plan_id: int, day_number: int, suffix: str = "", usage: Optional[Dict[str, Any]] = None
) -> str:
    """A workout's voice note (the summary, or follow-up questions with
    suffix "_followup"), stored as plan_<id>/day_<n><suffix>.ogg and spoken
    in the coach's cloned ElevenLabs voice, falling back to Sarvam. See
    generate_voice_note_at."""
    return generate_voice_note_at(
        analysis, f"plan_{plan_id}/day_{day_number}{suffix}.ogg", usage, prefer_elevenlabs=True
    )
