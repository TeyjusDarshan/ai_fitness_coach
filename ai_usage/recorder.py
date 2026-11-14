"""Records the cost of every paid AI call (Claude, Sarvam speech-to-text and
text-to-speech) as one ai_usage row, against the client and session it was
for. Shared by the backend and workout_analysis_consumer (a root package,
like stt/ and tts/).

Always best-effort: a failure to measure or record is logged and never
breaks the feature that made the call.
"""
import logging
import os
import re
import subprocess
from typing import Any, Dict, Iterable, Optional

from ai_usage.prices import claude_cost_usd, stt_cost_inr, tts_cost_inr, usd_inr_rate

logger = logging.getLogger(__name__)

_client = None
_feature_prefix = ""


def set_feature_prefix(prefix: str) -> None:
    """Tag every feature recorded from here on (e.g. "dry_run_" for the
    local dry-run scripts, so test spending is told apart from real use)."""
    global _feature_prefix
    _feature_prefix = prefix


def _supabase():
    global _client
    if _client is None:
        from supabase import create_client
        _client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    return _client


def _insert(row: Dict[str, Any]) -> None:
    _supabase().table("ai_usage").insert(row).execute()


def _record(row: Dict[str, Any]) -> None:
    rate = usd_inr_rate()
    usd, inr = row.get("cost_usd"), row.get("cost_inr")
    total = None
    if usd is not None or inr is not None:
        total = (usd or 0) * rate + (inr or 0)
    row = {
        **row,
        "feature": f"{_feature_prefix}{row['feature']}",
        "usd_inr_rate": rate,
        "cost_inr_total": round(total, 4) if total is not None else None,
        "cost_usd": round(usd, 6) if usd is not None else None,
        "cost_inr": round(inr, 4) if inr is not None else None,
    }
    try:
        _insert(row)
    except Exception:
        logger.exception("Failed to record AI usage: %s", row)


def record_claude(
    response: Any, feature: str, user_id: Optional[str] = None, session_id: Optional[int] = None
) -> None:
    """One Anthropic SDK response (messages.create / parse)."""
    try:
        usage = getattr(response, "usage", None)
        if usage is None or not isinstance(getattr(usage, "input_tokens", None), int):
            return
        model = getattr(response, "model", None)
        tokens = {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_tokens": getattr(usage, "cache_read_input_tokens", None) or 0,
            "cache_creation_tokens": getattr(usage, "cache_creation_input_tokens", None) or 0,
        }
        _record({
            "user_id": user_id, "session_id": session_id, "provider": "anthropic", "feature": feature,
            "model": model, **tokens, "cost_usd": claude_cost_usd(model, **tokens),
            "request_id": getattr(response, "id", None),
        })
    except Exception:
        logger.exception("Failed to measure Claude usage for feature=%s", feature)


def record_langchain(
    messages: Iterable[Any], feature: str, user_id: Optional[str] = None, session_id: Optional[int] = None
) -> None:
    """Every model turn of a LangChain agent run, summed into one row (a
    plan generation makes many calls)."""
    try:
        totals = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_creation_tokens": 0}
        model, calls = None, 0
        for message in messages:
            usage = getattr(message, "usage_metadata", None)
            if not usage:
                continue
            calls += 1
            details = usage.get("input_token_details") or {}
            cache_read = details.get("cache_read") or 0
            cache_creation = details.get("cache_creation") or 0
            # LangChain's input_tokens include the cached ones; price them apart.
            totals["input_tokens"] += max(0, (usage.get("input_tokens") or 0) - cache_read - cache_creation)
            totals["output_tokens"] += usage.get("output_tokens") or 0
            totals["cache_read_tokens"] += cache_read
            totals["cache_creation_tokens"] += cache_creation
            model = (getattr(message, "response_metadata", None) or {}).get("model_name") or model
        if not calls:
            return
        _record({
            "user_id": user_id, "session_id": session_id, "provider": "anthropic", "feature": feature,
            "model": model, **totals, "cost_usd": claude_cost_usd(model, **totals), "calls": calls,
        })
    except Exception:
        logger.exception("Failed to measure LangChain usage for feature=%s", feature)


def record_stt(
    audio: bytes, file_name: str, model: str, feature: str,
    user_id: Optional[str] = None, session_id: Optional[int] = None,
) -> None:
    """One Sarvam speech-to-text job: billed on the audio's length."""
    seconds = audio_seconds(audio)
    _record({
        "user_id": user_id, "session_id": session_id, "provider": "sarvam", "feature": feature,
        "model": model, "audio_seconds": round(seconds, 2) if seconds is not None else None,
        "cost_inr": stt_cost_inr(seconds),
    })


def record_tts(
    text: str, model: str, feature: str, user_id: Optional[str] = None, session_id: Optional[int] = None
) -> None:
    """One Sarvam text-to-speech call: billed per character."""
    characters = len(text or "")
    _record({
        "user_id": user_id, "session_id": session_id, "provider": "sarvam", "feature": feature,
        "model": model, "characters": characters, "cost_inr": tts_cost_inr(model, characters),
    })


_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")


def audio_seconds(audio: bytes) -> Optional[float]:
    """Length of an audio file in seconds, by decoding it with ffmpeg (the
    consumer already needs ffmpeg for voice notes). Decoding rather than
    reading the header, because browser-recorded webm often has no duration
    in its header. None if it can't be measured."""
    try:
        process = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", "pipe:0", "-f", "null", "-"],
            input=audio, capture_output=True, timeout=60,
        )
        matches = _TIME_RE.findall(process.stderr.decode("utf-8", "replace"))
        if not matches:
            return None
        hours, minutes, seconds = matches[-1]
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except Exception:
        logger.exception("Failed to measure audio length")
        return None
