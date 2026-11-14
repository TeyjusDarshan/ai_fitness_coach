import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Hashable, Optional

from ai_usage import record_stt

from blob_storage_manager import SupabaseBlobStorageManager
from stt import SarvamBatchSTTClient

logger = logging.getLogger(__name__)

# Must match backend/feedback_storage.py's FEEDBACK_BUCKET — this package is
# deployed independently of backend, so the name is duplicated rather than imported.
FEEDBACK_BUCKET = "voice-feedback"

# Sarvam batch jobs mostly wait on the server, so a few run side by side.
MAX_PARALLEL_TRANSCRIPTIONS = 4

_storage: Optional[SupabaseBlobStorageManager] = None
_stt_client: Optional[SarvamBatchSTTClient] = None


def _get_storage() -> SupabaseBlobStorageManager:
    global _storage
    if _storage is None:
        _storage = SupabaseBlobStorageManager(bucket=FEEDBACK_BUCKET)
    return _storage


def _get_stt_client() -> SarvamBatchSTTClient:
    global _stt_client
    if _stt_client is None:
        _stt_client = SarvamBatchSTTClient()
    return _stt_client


# Who an ai_usage row is for: {"feature", "user_id", "session_id"}.
Usage = Optional[Dict[str, Any]]


def transcribe_feedback(feedback_audio_path: str, usage: Usage = None) -> str:
    """Transcribe a voice note in the private voice-feedback bucket
    (sessions.feedback_audio_path, session_exercises.feedback_audio_path or
    a stored WhatsApp reply): download it, then run it through a Sarvam
    batch speech-to-text job.

    The clients are built on first use, not at import, so importing this
    module never needs storage or Sarvam credentials.
    """
    audio = _get_storage().download(feedback_audio_path)
    return transcribe_audio(audio, feedback_audio_path, usage)


def transcribe_audio(audio: bytes, file_name: str, usage: Usage = None) -> str:
    """Transcribe audio bytes (file_name's extension says the format), and
    record what it cost (billed on the audio's length) when `usage` says
    who it was for."""
    stt_client = _get_stt_client()
    transcript = stt_client.transcribe(audio, file_name)
    if usage:
        record_stt(audio, file_name, getattr(stt_client, "_model", None), **usage)
    return transcript


def transcribe_many(paths: Dict[Hashable, str], usage: Usage = None) -> Dict[Hashable, str]:
    """key -> transcript for each key -> voice-feedback path, transcribed in
    parallel. Best-effort per note: one that fails (or comes back empty) is
    logged and left out, so the rest still count."""
    if not paths:
        return {}

    def _one(path: str) -> Optional[str]:
        try:
            return transcribe_feedback(path, usage)
        except Exception:
            logger.exception("Failed to transcribe voice feedback at %s", path)
            return None

    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_TRANSCRIPTIONS, len(paths))) as pool:
        results = dict(zip(paths, pool.map(_one, paths.values())))
    return {key: text.strip() for key, text in results.items() if text and text.strip()}


def store_reply_audio(audio: bytes, name: str, content_type: str) -> str:
    """Keep a WhatsApp voice reply in the voice-feedback bucket; returns its
    object path (the bucket is private, so the returned URL isn't useful)."""
    _get_storage().store(audio, name, content_type=content_type)
    return name
