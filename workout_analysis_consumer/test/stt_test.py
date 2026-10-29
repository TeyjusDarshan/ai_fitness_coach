"""Tests for SarvamBatchSTTClient, with the SarvamAI SDK client mocked so
no audio is sent anywhere. The real Sarvam call is covered by the
integration test in feedback_test.py."""
import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stt import SarvamBatchSTTClient, TranscriptionError


def _mock_job(job_state="Completed", failed=(), output=None):
    """A mocked SpeechToTextJob whose download_outputs writes output (as the
    SDK does, to <output_dir>/<input file name>.json) unless it's None."""
    job = MagicMock(job_id="job_1")
    job.wait_until_complete.return_value = SimpleNamespace(job_state=job_state)
    job.get_file_results.return_value = {"successful": [], "failed": list(failed)}
    uploaded = []
    job.upload_files.side_effect = lambda file_paths: uploaded.extend(file_paths)

    def download_outputs(output_dir):
        os.makedirs(output_dir, exist_ok=True)
        if output is not None:
            name = os.path.basename(uploaded[0])
            with open(os.path.join(output_dir, f"{name}.json"), "w", encoding="utf-8") as f:
                json.dump(output, f)
        return True

    job.download_outputs.side_effect = download_outputs
    job.uploaded = uploaded
    return job


@pytest.fixture
def sarvam(monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    sdk = MagicMock()
    monkeypatch.setattr("stt.client.SarvamAI", MagicMock(return_value=sdk))
    return sdk


def test_transcribe_returns_the_stripped_transcript(sarvam):
    job = _mock_job(output={"transcript": "  இன்னைக்கு squats konjam kashtam  "})
    sarvam.speech_to_text_job.create_job.return_value = job

    result = SarvamBatchSTTClient().transcribe(b"audio-bytes", "session_48.webm")

    assert result == "இன்னைக்கு squats konjam kashtam"
    [uploaded] = job.uploaded
    assert os.path.basename(uploaded) == "session_48.webm"
    job.start.assert_called_once()


def test_transcribe_creates_a_tamil_codemix_saaras_v4_job(sarvam):
    sarvam.speech_to_text_job.create_job.return_value = _mock_job(output={"transcript": "x"})

    SarvamBatchSTTClient().transcribe(b"audio-bytes", "session_48.webm")

    sarvam.speech_to_text_job.create_job.assert_called_once_with(
        model="saaras:v4", mode="codemix", language_code="ta-IN"
    )


@pytest.mark.parametrize("job", [
    _mock_job(job_state="Failed"),
    _mock_job(failed=[{"file_name": "session_48.webm", "error_message": "unsupported format"}]),
    _mock_job(output=None),
], ids=["job failed", "file failed", "no output"])
def test_transcribe_raises_when_the_job_produces_no_transcript(sarvam, job):
    sarvam.speech_to_text_job.create_job.return_value = job

    with pytest.raises(TranscriptionError):
        SarvamBatchSTTClient().transcribe(b"audio-bytes", "session_48.webm")
