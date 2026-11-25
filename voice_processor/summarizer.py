import json
import logging
import os
from typing import Any, Dict, List

import anthropic
from ai_usage import record_claude
from dotenv import load_dotenv
from pydantic import BaseModel

from voice_processor.feedback_agent import Question
from voice_processor.prompts import WORKOUT_ANALYSIS_SYSTEM_PROMPT

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


class WorkoutSummary(BaseModel):
    """The Tanglish check-in (greeting, how the workout looked, at most one
    improvement) plus the clarifying questions spoken after it (see
    WORKOUT_ANALYSIS_SYSTEM_PROMPT). No intro or closing line: the note ends
    on the last question."""
    summary: str
    questions: List[Question]


def spoken_text(summary: WorkoutSummary, questions: List[Dict[str, Any]]) -> str:
    """The voice note's text: the check-in, then the (validated) questions."""
    parts = [summary.summary.strip()]
    parts.extend(question["text"] for question in questions)
    return " ".join(part for part in parts if part)


def generate_workout_summary(context: Dict[str, Any]) -> WorkoutSummary:
    """Turn one day's workout context into a Tanglish coach summary and the
    clarifying questions to ask after it."""
    user_content = json.dumps(context, indent=2, default=str, ensure_ascii=False)
    logger.info(
        "Workout analysis prompt for session_id=%s\n--- system ---\n%s\n--- user ---\n%s",
        context.get("session_id"), WORKOUT_ANALYSIS_SYSTEM_PROMPT, user_content,
    )
    response = client.beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=WORKOUT_ANALYSIS_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
        output_format=WorkoutSummary,
        # On a policy decline, the API re-runs the request on Anthropic's
        # recommended fallback model within the same call.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    # Billed even when it refuses, so recorded first.
    record_claude(
        response, "summary_questions", user_id=context.get("user_id"), session_id=context.get("session_id")
    )
    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise SummaryRefusedError(f"Claude declined to summarize (category: {category})")
    if response.parsed_output is None:
        raise ValueError(f"No structured summary returned (stop_reason={response.stop_reason})")
    return response.parsed_output
