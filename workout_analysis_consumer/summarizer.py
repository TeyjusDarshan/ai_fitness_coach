import json
import logging
import os
from typing import Any, Dict

import anthropic
from dotenv import load_dotenv

from workout_analysis_consumer.prompts import WORKOUT_ANALYSIS_SYSTEM_PROMPT

load_dotenv()

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-5-5"

# Reads ANTHROPIC_API_KEY from the environment.
client = anthropic.Anthropic(
    max_retries=2,
    timeout=float(os.getenv("CLAUDE_REQUEST_TIMEOUT_SECONDS", "120")),
)


class SummaryRefusedError(RuntimeError):
    """Claude's safety classifiers declined the request (and no fallback
    model took it), so there's no summary to save."""


def generate_workout_summary(context: Dict[str, Any]) -> str:
    """Turn one day's workout context into a Tanglish coach summary."""
    user_content = json.dumps(context, indent=2, default=str, ensure_ascii=False)
    logger.info(
        "Workout analysis prompt for session_id=%s\n--- system ---\n%s\n--- user ---\n%s",
        context.get("session_id"), WORKOUT_ANALYSIS_SYSTEM_PROMPT, user_content,
    )
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=WORKOUT_ANALYSIS_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
        # On a policy decline, the API re-runs the request on Anthropic's
        # recommended fallback model within the same call.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise SummaryRefusedError(f"Claude declined to summarize (category: {category})")
    return "".join(block.text for block in response.content if block.type == "text").strip()
