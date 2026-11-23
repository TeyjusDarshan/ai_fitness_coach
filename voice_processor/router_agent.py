"""The router's Claude call: which processor should handle one WhatsApp
message from a client (voice_processor/router.py).

Claude Haiku returns a label from `allowed_labels` only (the label is an
enum built per call), plus the day the food was eaten and a short reason.
It only decides; the router's code acts on the decision.
"""
import json
import logging
import os
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, List, Literal, Optional, Tuple

import anthropic
from ai_usage import record_claude
from dotenv import load_dotenv
from pydantic import BaseModel, create_model

from voice_processor.router_prompts import ROUTER_SYSTEM_PROMPT

load_dotenv()

logger = logging.getLogger(__name__)

ROUTER_MODEL = "claude-haiku-5-5"
FEATURE = "message_routing"

DIET_CHECKIN, QUESTION_REPLY, OTHER = "diet_checkin", "question_reply", "other"
LABELS = (DIET_CHECKIN, QUESTION_REPLY, OTHER)

client = anthropic.Anthropic(timeout=float(os.getenv("ROUTER_TIMEOUT_SECONDS", "30")))


class RouterRefusedError(RuntimeError):
    """Claude declined to sort the message."""


@lru_cache(maxsize=8)
def route_schema(labels: Tuple[str, ...]) -> type:
    """The output model for one set of allowed labels."""
    return create_model(
        "RouteDecision",
        label=(Literal[labels], ...),
        day=(Literal["today", "yesterday"], ...),
        reason=(str, ...),
        __base__=BaseModel,
    )


def build_payload(
    message: str,
    message_type: str,
    allowed_labels: List[str],
    now: datetime,
    open_questions: Optional[List[Dict[str, Any]]] = None,
    minutes_since_asked: Optional[int] = None,
    meal_reminder: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "message": message,
        "message_type": message_type,
        "now": now.strftime("%A %d %B %Y, %H:%M"),
        "allowed_labels": allowed_labels,
    }
    if open_questions:
        payload["open_questions"] = [{"id": q.get("id"), "text": q.get("text")} for q in open_questions]
        payload["minutes_since_asked"] = minutes_since_asked
    if meal_reminder:
        payload["meal_reminder"] = meal_reminder
    return payload


def classify_message(payload: Dict[str, Any], user_id: Optional[str] = None) -> Any:
    """{label, day, reason} for one message (see build_payload)."""
    labels = tuple(label for label in LABELS if label in payload["allowed_labels"])
    user_content = json.dumps(payload, ensure_ascii=False, indent=2)
    response = client.beta.messages.parse(
        model=ROUTER_MODEL,
        max_tokens=2000,
        system=ROUTER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
        output_format=route_schema(labels),
        output_config={"effort": "low"},
    )
    # Billed even when it refuses, so recorded first.
    record_claude(response, FEATURE, user_id=user_id)
    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise RouterRefusedError(f"Claude declined ({FEATURE}, category: {category})")
    if response.parsed_output is None:
        raise ValueError(f"No structured output for {FEATURE} (stop_reason={response.stop_reason})")
    return response.parsed_output
