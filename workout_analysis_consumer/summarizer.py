import json
import os
from typing import Any, Dict

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_mistralai import ChatMistralAI

from workout_analysis_consumer.prompts import WORKOUT_ANALYSIS_SYSTEM_PROMPT

load_dotenv()

rate_limiter = InMemoryRateLimiter(
    requests_per_second=0.5,  # match the free-tier pacing used elsewhere in this project
    check_every_n_seconds=0.1,
    max_bucket_size=1,
)

llm = ChatMistralAI(
    model="mistral-large-latest",
    temperature=0.5,
    max_retries=2,
    timeout=int(os.getenv("MISTRAL_REQUEST_TIMEOUT_SECONDS", "120")),
    rate_limiter=rate_limiter,
)


def generate_workout_summary(context: Dict[str, Any]) -> str:
    """Turn one day's workout context into a Tanglish coach summary."""
    messages = [
        SystemMessage(content=WORKOUT_ANALYSIS_SYSTEM_PROMPT),
        HumanMessage(content=json.dumps(context, indent=2, default=str)),
    ]
    response = llm.invoke(messages)
    return response.content.strip()
