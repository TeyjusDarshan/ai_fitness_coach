from blob_storage_manager import SupabaseBlobStorageManager
from tts import SarvamTTSClient, mp3_to_whatsapp_ogg

_tts_client = SarvamTTSClient()
_blob_storage = SupabaseBlobStorageManager()


def generate_voice_note(analysis: str, plan_id: int, day_number: int, suffix: str = "") -> str:
    """Turn a Tanglish analysis into a WhatsApp-ready voice note and return
    its public URL: Sarvam TTS -> mp3, transcoded to mono OGG/Opus, uploaded
    to the voice-notes bucket. suffix tells apart another note for the same
    day (e.g. "_followup" for follow-up questions).
    """
    mp3_bytes = _tts_client.convert(analysis)
    ogg_bytes = mp3_to_whatsapp_ogg(mp3_bytes)
    name = f"plan_{plan_id}/day_{day_number}{suffix}.ogg"
    return _blob_storage.store(ogg_bytes, name)
