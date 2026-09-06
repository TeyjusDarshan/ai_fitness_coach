import json
import os
from typing import Any, Dict

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_google_genai import ChatGoogleGenerativeAI

from workout_analysis_consumer.prompts import WORKOUT_ANALYSIS_SYSTEM_PROMPT

load_dotenv()


rate_limiter = InMemoryRateLimiter(
    requests_per_second=0.15,  # conservative free-tier guess for gemini-3.8-flash; check aistudio.google.com/rate-limit and raise if you're on a paid tier
    check_every_n_seconds=0.1,
    max_bucket_size=1,
)

llm = ChatGoogleGenerativeAI(
    model="gemini-3.6-flash",
    temperature=0.5,
    max_retries=2,
    timeout=int(os.getenv("GEMINI_REQUEST_TIMEOUT_SECONDS", "120")),
    rate_limiter=rate_limiter,
)


def generate_workout_summary(context: Dict[str, Any]) -> str:
    """Turn one day's workout context into a Tanglish coach summary."""
    messages = [
        SystemMessage(content=WORKOUT_ANALYSIS_SYSTEM_PROMPT),
        HumanMessage(content=json.dumps(context, indent=2, default=str)),
    ]
    response = llm.invoke(messages)
    return _extract_text(response.content).strip()


def _extract_text(content: Any) -> str:
    """Normalize response content, which may be a plain string or a list of
    content blocks (e.g. [{'type': 'text', 'text': ..., 'extras': {...}}])."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
            if not isinstance(block, dict) or block.get("type", "text") == "text"
        )
    return str(content)
