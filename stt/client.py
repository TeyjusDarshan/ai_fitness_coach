import json
import os
import tempfile
from abc import ABC, abstractmethod

from dotenv import load_dotenv
from sarvamai import SarvamAI

load_dotenv()


class TranscriptionError(RuntimeError):
    """Raised when a speech-to-text job fails or returns no transcript."""


class STTClient(ABC):
    """Abstract base for speech-to-text providers."""

    @abstractmethod
    def transcribe(self, audio: bytes, file_name: str) -> str:
        """Transcribe audio (file_name's extension says its format) and
        return the transcript text."""
        raise NotImplementedError


class SarvamBatchSTTClient(STTClient):
    """STTClient implementation backed by the Sarvam AI batch speech-to-text
    API: create a job, upload the file, start it, poll until it finishes,
    then download its JSON output.

    timeout defaults to STT_JOB_TIMEOUT_SECONDS (180 s) rather than the SDK's
    600 s, since the analysis consumer handles one Kafka message at a time
    and must poll again within max.poll.interval.ms (300 s by default).
    """

    def __init__(
        self,
        language_code: str = "ta-IN",
        model: str = "saaras:v4",
        mode: str = "codemix",
        poll_interval: int = 5,
        timeout: int = int(os.getenv("STT_JOB_TIMEOUT_SECONDS", "180")),
    ):
        self._client = SarvamAI(api_subscription_key=os.environ["SARVAM_API_KEY"])
        self._language_code = language_code
        self._model = model
        self._mode = mode
        self._poll_interval = poll_interval
        self._timeout = timeout

    def transcribe(self, audio: bytes, file_name: str) -> str:
        job = self._client.speech_to_text_job.create_job(
            model=self._model,
            mode=self._mode,
            language_code=self._language_code,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            # The SDK uploads by path, under the file's base name.
            file_name = os.path.basename(file_name)
            audio_path = os.path.join(tmpdir, file_name)
            with open(audio_path, "wb") as f:
                f.write(audio)
            job.upload_files(file_paths=[audio_path])
            job.start()

            status = job.wait_until_complete(poll_interval=self._poll_interval, timeout=self._timeout)
            if status.job_state.lower() != "completed":
                raise TranscriptionError(f"Sarvam STT job {job.job_id} ended in state {status.job_state}")
            failed = job.get_file_results()["failed"]
            if failed:
                raise TranscriptionError(
                    f"Sarvam STT job {job.job_id} failed for {file_name}: {failed[0].get('error_message')}"
                )

            output_dir = os.path.join(tmpdir, "outputs")
            job.download_outputs(output_dir=output_dir)
            # download_outputs writes each input's result to <input file name>.json.
            output_path = os.path.join(output_dir, f"{file_name}.json")
            if not os.path.exists(output_path):
                raise TranscriptionError(f"Sarvam STT job {job.job_id} produced no output for {file_name}")
            with open(output_path, encoding="utf-8") as f:
                return (json.load(f).get("transcript") or "").strip()
