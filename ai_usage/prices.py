"""Unit prices for every paid AI call the app makes. Update here when a
provider changes its prices; each ai_usage row stores the cost computed at
the time of the call, so past rows keep what they cost then.

Claude: USD per million tokens (https://platform.claude.com pricing).
Sarvam: INR, pay-as-you-go, excluding GST
(https://docs.sarvam.ai/api/getting-started/pricing).
"""
import os

# model -> (input, output, cache read, cache write) USD per million tokens.
# Cache writes are 1.25x input (5-minute cache).
CLAUDE_PRICES_USD_PER_MTOK = {
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00, 0.10, 2.50),
    "claude-sonnet-5": (2.00, 10.00, 0.20, 2.50),
    "claude-opus-5": (5.00, 25.00, 0.50, 6.25),
    "claude-opus-4-8": (5.00, 25.00, 0.50, 6.25),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}

# Speech to text (saaras, batch/real-time/streaming): per minute, billed per second.
SARVAM_STT_INR_PER_MINUTE = 0.49
# Text to speech, bulbul:v3: per 1,000 characters.
SARVAM_TTS_INR_PER_1K_CHARS = {"bulbul:v3": 3.00, "bulbul:v4-flash": 1.00}

DEFAULT_USD_INR_RATE = 94.0


def usd_inr_rate() -> float:
    try:
        return float(os.getenv("USD_INR_RATE", DEFAULT_USD_INR_RATE))
    except ValueError:
        return DEFAULT_USD_INR_RATE


def claude_cost_usd(model, input_tokens, output_tokens, cache_read_tokens=0, cache_creation_tokens=0):
    """USD for one Claude call, or None for a model not in the table."""
    prices = CLAUDE_PRICES_USD_PER_MTOK.get(_base_model(model))
    if prices is None:
        return None
    input_price, output_price, cache_read_price, cache_write_price = prices
    return (
        (input_tokens or 0) * input_price
        + (output_tokens or 0) * output_price
        + (cache_read_tokens or 0) * cache_read_price
        + (cache_creation_tokens or 0) * cache_write_price
    ) / 1_000_000


def stt_cost_inr(seconds):
    """INR for transcribing `seconds` of audio (billed per whole second)."""
    if seconds is None:
        return None
    import math
    return math.ceil(seconds) * SARVAM_STT_INR_PER_MINUTE / 60


def tts_cost_inr(model, characters):
    price = SARVAM_TTS_INR_PER_1K_CHARS.get(model)
    if price is None or characters is None:
        return None
    return characters * price / 1000


def _base_model(model):
    """Strip a date suffix some responses carry (e.g. claude-x-20260101)."""
    model = (model or "").strip()
    if model in CLAUDE_PRICES_USD_PER_MTOK:
        return model
    parts = model.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 8:
        return parts[0]
    return model
