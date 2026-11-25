import base64
import os
from abc import ABC, abstractmethod

from dotenv import load_dotenv
from sarvamai import SarvamAI

load_dotenv()


class TTSClient(ABC):
    """Abstract base for text-to-speech providers. Subclasses set `provider`
    (ai_usage.provider) and `_model` (the model billed)."""

    provider: str = ""
    _model: str = ""

    @abstractmethod
    def convert(self, text: str) -> bytes:
        """Convert text to audio and return the raw audio bytes."""
        raise NotImplementedError


class SarvamTTSClient(TTSClient):
    """TTSClient implementation backed by the Sarvam AI text-to-speech API."""

    provider = "sarvam"

    def __init__(
        self,
        language_code: str = "ta-IN",
        speaker: str = "shubh",
        model: str = "bulbul:v3",
        pace: float = 1.1,
        speech_sample_rate: int = 22050,
        output_audio_codec="mp3"

    ):
        self._client = SarvamAI(api_subscription_key=os.environ["SARVAM_API_KEY"])
        self._language_code = language_code
        self._speaker = speaker
        self._model = model
        self._pace = pace
        self._speech_sample_rate = speech_sample_rate
        self.output_audio_codec = output_audio_codec

    def convert(self, text: str) -> bytes:
        response = self._client.text_to_speech.convert(
            text=text,
            language_code=self._language_code,
            speaker=self._speaker,
            model=self._model,
            pace=self._pace,
            speech_sample_rate=self._speech_sample_rate,
            output_audio_codec=self.output_audio_codec
        )
        return base64.b64decode(response.audios[0])


class ElevenLabsTTSClient(TTSClient):
    """TTSClient backed by ElevenLabs, speaking in a cloned voice. Used for
    the workout summary and follow-up voice notes (voice_processor/voice.py);
    returns mp3, so the existing mp3 -> WhatsApp OGG step is unchanged.

    Reads ELEVENLABS_API_KEY; the voice and model default to
    ELEVENLABS_VOICE_ID and ELEVENLABS_MODEL_ID (eleven_v4_turbo). Plain text,
    no audio tags. Default voice settings, as tested."""

    provider = "elevenlabs"

    def __init__(
        self,
        voice_id: str = None,
        model: str = None,
        language_code: str = "ta",
        output_format: str = "mp3_44100_128",
    ):
        from elevenlabs.client import ElevenLabs

        self._client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"], timeout=120)
        self._voice_id = voice_id or os.environ["ELEVENLABS_VOICE_ID"]
        self._model = model or os.getenv("ELEVENLABS_MODEL_ID", "eleven_v4_turbo")
        self._language_code = language_code
        self._output_format = output_format

    def convert(self, text: str) -> bytes:
        audio = self._client.text_to_speech.convert(
            voice_id=self._voice_id,
            text=text,
            model_id=self._model,
            language_code=self._language_code,
            output_format=self._output_format,
        )
        return b"".join(audio)
