"""Speech to text for a meal recording in the private voice-feedback
bucket (meal_logs.audio_path)."""
import logging
from typing import Any, Dict, Optional, Tuple

from ai_usage import audio_seconds, record_stt
from blob_storage_manager import SupabaseBlobStorageManager
from stt import SarvamBatchSTTClient, SarvamRestSTTClient

logger = logging.getLogger(__name__)

# Must match backend/feedback_storage.py's FEEDBACK_BUCKET.
FEEDBACK_BUCKET = "voice-feedback"
# Under the fast endpoint's 30 s limit, with room for measuring error.
FAST_MAX_SECONDS = 28

_storage: Optional[SupabaseBlobStorageManager] = None


def _get_storage() -> SupabaseBlobStorageManager:
    global _storage
    if _storage is None:
        _storage = SupabaseBlobStorageManager(bucket=FEEDBACK_BUCKET)
    return _storage


def transcribe_audio_unrecorded(audio: bytes, file_name: str) -> Tuple[str, Optional[str]]:
    """(transcript, model) of a recording, without recording its cost — for
    a caller that only knows afterwards which feature to bill it to (the
    WhatsApp router). A short one goes to Sarvam's synchronous endpoint (a
    couple of seconds, so she isn't kept waiting); a longer one, or one the
    fast endpoint fails on, goes through a batch job."""
    seconds = audio_seconds(audio)
    client = None
    transcript = None
    if seconds is not None and seconds <= FAST_MAX_SECONDS:
        try:
            client = SarvamRestSTTClient()
            transcript = client.transcribe(audio, file_name)
        except Exception:
            logger.exception("Fast transcription failed for %s; using a batch job", file_name)
            transcript = None
    if transcript is None:
        client = SarvamBatchSTTClient()
        transcript = client.transcribe(audio, file_name)
    return transcript, getattr(client, "_model", None)


def transcribe_audio(audio: bytes, file_name: str, user_id: Optional[str] = None) -> str:
    """Transcript of a recording, its cost recorded as `meal_stt`."""
    transcript, model = transcribe_audio_unrecorded(audio, file_name)
    record_stt(audio, file_name, model, "meal_stt", user_id=user_id)
    return transcript


def transcribe_meal_log(log: Dict[str, Any]) -> str:
    """What she said in a meal log's recording."""
    audio = _get_storage().download(log["audio_path"])
    return transcribe_audio(audio, log["audio_path"], log.get("user_id"))
