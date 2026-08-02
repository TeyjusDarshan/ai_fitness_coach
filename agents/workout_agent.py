import json
import re
from string import Template
from typing import Any, Dict

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_mistralai import ChatMistralAI

from agents.prompts_v1 import DAY_TEMPLATES, WORKOUT_AGENT_V1_SYSTEM_PROMPT_TEMPLATE
from agents.tools.workout_tools import WORKOUT_TOOLS_V1
from langchain_core.rate_limiters import InMemoryRateLimiter


load_dotenv()

rate_limiter = InMemoryRateLimiter(
    requests_per_second=0.5,   # e.g. 1 request every 2 seconds — match your actual free-tier limit
    check_every_n_seconds=0.1, # how often it checks if a slot has opened up
    max_bucket_size=1,         # burst allowance; keep at 1 for a tight free tier
)

llm = ChatMistralAI(
    model="mistral-large-latest",
    temperature=0.1,
    max_retries=2,
    rate_limiter=rate_limiter
)

_prompt_template = Template(WORKOUT_AGENT_V1_SYSTEM_PROMPT_TEMPLATE)
SYSTEM_PROMPT_V1 = _prompt_template.substitute(
    day_template_reference=json.dumps(DAY_TEMPLATES, indent=2),
)

# The agent now makes one search_exercises_by_movement tool call per slot
# (plus fallback/superset slots), which for a 4-day plan can mean 15+ tool
# round trips. The default langgraph recursion limit (25 graph steps) is too
# tight for that, so we raise it for this agent's invocations.
AGENT_INVOKE_CONFIG = {"recursion_limit": 100}


def select_plan_type(days_per_week: Any) -> str:
    """Deterministic plan-type gate: <=3 days/week -> 3_day, >=4 -> 4_day.

    Computed in Python (not left to the model) so this business rule can
    never be mis-applied; the prompt still restates and validates it.
    """
    try:
        days = int(days_per_week)
    except (TypeError, ValueError):
        days = 3  # missing/invalid input -> conservative default
    if days <= 0:
        days = 3
    return "3_day" if days <= 3 else "4_day"


def _extract_json(text: str) -> str:
    """Pull the JSON object out of the model's response.

    The prompt demands bare JSON with no surrounding text, but the model
    sometimes adds a conversational preamble before a ```json fence anyway.
    Prefer a fenced block if present, then narrow to the outermost {...} so
    stray prose before/after it doesn't break parsing.
    """
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end < start:
        return candidate.strip()
    return candidate[start:end + 1]


def generate_workout_plan_v1(user_profile: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a full 7-day (3-day or 4-day) plan for a single client profile.

    Selects the plan type from availability.days_per_week, then runs a
    tool-using LLM agent that fills the fixed day template with real
    exercises fetched live via search_exercises_by_movement, subject to the
    safety guardrails coded into SYSTEM_PROMPT_V1.
    """
    days_per_week = (user_profile.get("availability") or {}).get("days_per_week")
    plan_type = select_plan_type(days_per_week)
    day_template = DAY_TEMPLATES[plan_type]

    agent = create_agent(
        model=llm,
        tools=WORKOUT_TOOLS_V1,
        system_prompt=SYSTEM_PROMPT_V1,
    )

    request_payload = {
        "client_profile": user_profile,
        "selected_plan_type": plan_type,
        "day_template": day_template,
    }
    agent_response = agent.invoke(
        {"messages": [HumanMessage(content=json.dumps(request_payload, indent=2))]},
        config=AGENT_INVOKE_CONFIG,
    )
    raw_text = agent_response["messages"][-1].content

    try:
        return json.loads(_extract_json(raw_text))
    except json.JSONDecodeError as e:
        return {
            "error": f"Failed to parse agent output as JSON: {e}",
            "plan_type": plan_type,
            "raw_response": raw_text,
        }


if __name__ == "__main__":
    from agents.mock_data_v1 import SAMPLE_USER_PROFILE_V1, SAMPLE_USER_PROFILE_V1_FOUR_DAY

    plan = generate_workout_plan_v1(SAMPLE_USER_PROFILE_V1_FOUR_DAY)
    print(json.dumps(plan, indent=2))
