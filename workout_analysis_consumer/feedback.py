from typing import Optional

from blob_storage_manager import SupabaseBlobStorageManager
from stt import SarvamBatchSTTClient

# Must match backend/feedback_storage.py's FEEDBACK_BUCKET — this package is
# deployed independently of backend, so the name is duplicated rather than imported.
FEEDBACK_BUCKET = "voice-feedback"

_storage: Optional[SupabaseBlobStorageManager] = None
_stt_client: Optional[SarvamBatchSTTClient] = None


def transcribe_feedback(feedback_audio_path: str) -> str:
    """Transcribe the client's recorded voice feedback for a session
    (sessions.feedback_audio_path in the private voice-feedback bucket):
    download it, then run it through a Sarvam batch speech-to-text job.

    The clients are built on first use, not at import, so importing this
    module never needs storage or Sarvam credentials.
    """
    global _storage, _stt_client
    if _storage is None:
        _storage = SupabaseBlobStorageManager(bucket=FEEDBACK_BUCKET)
    if _stt_client is None:
        _stt_client = SarvamBatchSTTClient()
    audio = _storage.download(feedback_audio_path)
    return _stt_client.transcribe(audio, feedback_audio_path)
