import base64
import os
from abc import ABC, abstractmethod

from dotenv import load_dotenv
from sarvamai import SarvamAI

load_dotenv()


class TTSClient(ABC):
    """Abstract base for text-to-speech providers."""

    @abstractmethod
    def convert(self, text: str) -> bytes:
        """Convert text to audio and return the raw audio bytes."""
        raise NotImplementedError


class SarvamTTSClient(TTSClient):
    """TTSClient implementation backed by the Sarvam AI text-to-speech API."""

    def __init__(
        self,
        language_code: str = "ta-IN",
        speaker: str = "pooja",
        model: str = "bulbul:v3",
        pace: float = 1.2,
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
