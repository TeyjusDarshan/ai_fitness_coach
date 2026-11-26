"""The AI Coach agent: one structured-output Claude call over a scheduled
session's plain-text context (context.build_context: the client summary,
the last 7 days, the same day in the previous two weeks, and the workout),
returning one suggestion per exercise. The output is only a proposal —
validate.validate_suggestions checks it before it's stored, and the coach
accepts or rejects each one."""
import logging
import os
from typing import List, Literal, Optional

import anthropic
from ai_usage import record_claude
from dotenv import load_dotenv
from pydantic import BaseModel

from backend.coach_agent.prompts import COACH_AGENT_SYSTEM_PROMPT

load_dotenv()

logger = logging.getLogger(__name__)

# Was claude-opus-5-5 until 2026-11-26; quality is held by the
# validator and the coach accepting each suggestion. Overridable to roll back.
MODEL = os.getenv("COACH_AGENT_MODEL", "claude-sonnet-5-5")
EFFORT = "medium"

# Runs inside an admin request, so it must finish well within the
# function's time limit; no retries for the same reason.
client = anthropic.Anthropic(
    max_retries=0,
    timeout=float(os.getenv("COACH_AGENT_TIMEOUT_SECONDS", "55")),
)

Action = Literal["keep", "adjust", "progress", "regress", "skip"]
# The input sections (context.SOURCES) a quote can come from.
EvidenceSource = Literal["workout", "summary", "last_7_days", "same_day_history"]


class Evidence(BaseModel):
    source: EvidenceSource
    quote: str
    date: Optional[str]


class ExerciseSuggestion(BaseModel):
    session_exercise_id: int
    action: Action
    sets: Optional[int]
    reps: Optional[List[int]]
    to_exercise_id: Optional[int]
    reason: str
    evidence: List[Evidence]


class SessionSuggestions(BaseModel):
    overview: str
    exercises: List[ExerciseSuggestion]


class CoachAgentRefusedError(RuntimeError):
    """Claude declined (and no fallback model took the request)."""


def suggest(
    context: str, user_id: Optional[str] = None, session_id: Optional[int] = None
) -> SessionSuggestions:
    response = client.beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=COACH_AGENT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context}],
        output_format=SessionSuggestions,
        output_config={"effort": EFFORT},
        # On a policy decline, the API re-runs the request on Anthropic's
        # recommended fallback model within the same call.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    # Billed even when it refuses, so recorded first.
    record_claude(response, "coach_suggestions", user_id=user_id, session_id=session_id)
    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise CoachAgentRefusedError(f"Claude declined (category: {category})")
    if response.parsed_output is None:
        raise ValueError(f"No structured output (stop_reason={response.stop_reason})")
    return response.parsed_output
