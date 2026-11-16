"""Voice feedback recordings: the private `voice-feedback` Supabase Storage
bucket, one object per session (`session_<id>.<ext>`, its path kept in
sessions.feedback_audio_path) and per exercise of a session
(`session_<id>_exercise_<session_exercise_id>.<ext>`, kept in
session_exercises.feedback_audio_path). The bucket is private, so recordings are only
ever read through short-lived signed URLs."""
from typing import Optional, Tuple

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


class UploadError(Exception):
    """Why an uploaded recording was refused: a message for the client and
    the HTTP status to answer with."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.message = message
        self.status = status


def read_audio_upload(upload) -> Tuple[str, bytes]:
    """(content type, bytes) of an uploaded recording (a multipart file),
    or UploadError if it's missing, not a supported audio type, empty or
    over MAX_FEEDBACK_BYTES."""
    if upload is None:
        raise UploadError("An 'audio' file is required.", 400)
    content_type = (upload.mimetype or "").split(";")[0].strip().lower()
    if content_type not in EXTENSIONS_BY_CONTENT_TYPE:
        raise UploadError(f"Unsupported audio type '{content_type}'.", 415)
    data = upload.read(MAX_FEEDBACK_BYTES + 1)
    if not data:
        raise UploadError("The recording is empty.", 400)
    if len(data) > MAX_FEEDBACK_BYTES:
        raise UploadError("The recording is too long.", 413)
    return content_type, data


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


def exercise_feedback_path(session_id: int, session_exercise_id: int, content_type: str) -> Optional[str]:
    extension = EXTENSIONS_BY_CONTENT_TYPE.get(content_type)
    return f"session_{session_id}_exercise_{session_exercise_id}.{extension}" if extension else None


def meal_audio_path(meal_log_id: int, content_type: str) -> Optional[str]:
    """Where a meal recording is kept (meal_logs.audio_path)."""
    extension = EXTENSIONS_BY_CONTENT_TYPE.get(content_type)
    return f"meal_{meal_log_id}.{extension}" if extension else None
