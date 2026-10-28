"""Voice feedback recordings: the private `voice-feedback` Supabase Storage
bucket, one object per session (`session_<id>.<ext>`), its path kept in
sessions.feedback_audio_path. The bucket is private, so recordings are only
ever read through short-lived signed URLs."""
from typing import Optional

from blob_storage_manager import BlobStorageManager, SupabaseBlobStorageManager

FEEDBACK_BUCKET = "voice-feedback"
SIGNED_URL_TTL_SECONDS = 60 * 60

# What MediaRecorder produces: webm/ogg (Chrome, Firefox), mp4 (Safari).
EXTENSIONS_BY_CONTENT_TYPE = {
    "audio/webm": "webm",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/aac": "aac",
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
}

# Vercel functions reject request bodies over 4.5 MB; stay under it.
MAX_FEEDBACK_BYTES = 4 * 1024 * 1024

_storage: Optional[BlobStorageManager] = None


def feedback_storage() -> BlobStorageManager:
    """Built on first use, not at import, so the app still boots where the
    storage credentials aren't available."""
    global _storage
    if _storage is None:
        _storage = SupabaseBlobStorageManager(bucket=FEEDBACK_BUCKET)
    return _storage


def feedback_path(session_id: int, content_type: str) -> Optional[str]:
    extension = EXTENSIONS_BY_CONTENT_TYPE.get(content_type)
    return f"session_{session_id}.{extension}" if extension else None
