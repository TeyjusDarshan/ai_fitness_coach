import subprocess

FFMPEG_BINARY = "ffmpeg"

# WhatsApp only accepts voice notes as mono OGG/Opus; 16kHz/32kbps is the
# standard rate for speech-only Opus audio (WhatsApp's own voice notes use it).
OPUS_SAMPLE_RATE = 16000
OPUS_BITRATE = "32k"


class AudioConversionError(RuntimeError):
    """Raised when ffmpeg fails to transcode audio."""


def mp3_to_whatsapp_ogg(mp3_bytes: bytes) -> bytes:
    """Transcode MP3 audio bytes into a mono OGG/Opus voice note for WhatsApp."""
    try:
        process = subprocess.run(
            [
                FFMPEG_BINARY,
                "-loglevel", "error",
                "-i", "pipe:0",
                "-vn",
                "-ac", "1",
                "-ar", str(OPUS_SAMPLE_RATE),
                "-c:a", "libopus",
                "-b:a", OPUS_BITRATE,
                "-f", "ogg",
                "pipe:1",
            ],
            input=mp3_bytes,
            capture_output=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise AudioConversionError(
            "ffmpeg is not installed or not on PATH"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise AudioConversionError(
            f"ffmpeg failed to convert mp3 to ogg: {exc.stderr.decode('utf-8', errors='replace')}"
        ) from exc

    return process.stdout
