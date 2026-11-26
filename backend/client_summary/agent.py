"""The client summary's Claude call: Sonnet 5.5 at medium effort, structured
output ({summary}), with one shortening pass if it runs over the word limit.

Runs inside an admin request, so it must finish well within the function's
time limit; no retries for the same reason."""
import logging
import os
from typing import Optional

import anthropic
from ai_usage import record_claude
from dotenv import load_dotenv
from pydantic import BaseModel

from backend.client_summary.prompts import CLIENT_SUMMARY_SYSTEM_PROMPT, MAX_WORDS, SHORTEN_SYSTEM_PROMPT

load_dotenv()

logger = logging.getLogger(__name__)

MODEL = os.getenv("CLIENT_SUMMARY_MODEL", "claude-sonnet-5-5")
EFFORT = "medium"
FEATURE = "client_summary"

client = anthropic.Anthropic(
    max_retries=0,
    timeout=float(os.getenv("CLIENT_SUMMARY_TIMEOUT_SECONDS", "55")),
)


class ClientSummary(BaseModel):
    summary: str


class ClientSummaryRefusedError(RuntimeError):
    """Claude declined (and no fallback model took the request)."""


def word_count(text: str) -> int:
    return len(text.split())


def _call(system: str, content: str, effort: str, user_id: Optional[str], feature: str) -> tuple:
    response = client.beta.messages.parse(
        model=MODEL,
        max_tokens=8000,
        system=system,
        messages=[{"role": "user", "content": content}],
        output_format=ClientSummary,
        output_config={"effort": effort},
        # On a policy decline, the API re-runs the request on Anthropic's
        # recommended fallback model within the same call.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    # Billed even when it refuses, so recorded first.
    record_claude(response, feature, user_id=user_id)
    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise ClientSummaryRefusedError(f"Claude declined (category: {category})")
    if response.parsed_output is None:
        raise ValueError(f"No structured output (stop_reason={response.stop_reason})")
    return response.parsed_output.summary.strip(), response.model


def summarize(user_message: str, user_id: Optional[str] = None) -> tuple:
    """(summary text, model that answered). Over MAX_WORDS → one cheap
    shortening pass (the draft only, with its word count); if that still runs over,
    the shorter of the two is kept and a warning logged."""
    text, model = _call(CLIENT_SUMMARY_SYSTEM_PROMPT, user_message, EFFORT, user_id, FEATURE)
    if word_count(text) <= MAX_WORDS:
        return text, model
    logger.info("Client summary for %s ran to %d words; shortening", user_id, word_count(text))
    draft = f"Word count: {word_count(text)} (limit {MAX_WORDS}).\n\n{text}"
    shorter, _ = _call(SHORTEN_SYSTEM_PROMPT, draft, "medium", user_id, f"{FEATURE}_shorten")
    if word_count(shorter) > MAX_WORDS:
        logger.warning("Client summary for %s still %d words after shortening", user_id, word_count(shorter))
    return (shorter if word_count(shorter) < word_count(text) else text), model
