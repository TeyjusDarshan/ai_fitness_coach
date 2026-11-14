"""The AI Coach agent: one structured-output Claude call over a scheduled
session's context, returning one suggestion per exercise. The output is only
a proposal — validate.validate_suggestions checks it before it's stored, and
the coach accepts or rejects each one."""
import json
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

MODEL = "claude-opus-5-5"
EFFORT = "medium"

# Runs inside an admin request, so it must finish well within the
# function's time limit; no retries for the same reason.
client = anthropic.Anthropic(
    max_retries=0,
    timeout=float(os.getenv("COACH_AGENT_TIMEOUT_SECONDS", "55")),
)

Action = Literal["keep", "adjust", "progress", "regress", "skip"]
EvidenceSource = Literal[
    "client_answer", "client_comment", "set_logs", "rpe",
    "joint_pain", "profile", "coach_note", "progression_rule",
]


class Evidence(BaseModel):
    source: EvidenceSource
    quote: str
    session_id: Optional[int]


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


def user_content(context: dict) -> str:
    return json.dumps(context, indent=2, default=str, ensure_ascii=False)


def suggest(context: dict, user_id: Optional[str] = None) -> SessionSuggestions:
    response = client.beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=COACH_AGENT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content(context)}],
        output_format=SessionSuggestions,
        output_config={"effort": EFFORT},
        # On a policy decline, the API re-runs the request on Anthropic's
        # recommended fallback model within the same call.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    # Billed even when it refuses, so recorded first.
    record_claude(
        response, "coach_suggestions", user_id=user_id, session_id=(context.get("session") or {}).get("session_id")
    )
    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise CoachAgentRefusedError(f"Claude declined (category: {category})")
    if response.parsed_output is None:
        raise ValueError(f"No structured output (stop_reason={response.stop_reason})")
    return response.parsed_output
