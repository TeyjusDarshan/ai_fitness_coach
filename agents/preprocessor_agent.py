import json
import uuid
from string import Template
from typing import Any, Dict

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_google_genai import ChatGoogleGenerativeAI

from agents.mock_data_v1 import SAMPLE_USER_PROFILE_V1
from agents.prompts_preprocessor import PREPROCESSOR_SYSTEM_PROMPT_TEMPLATE
from agents.workout_agent import generate_workout_plan_v1

load_dotenv()

rate_limiter = InMemoryRateLimiter(
    requests_per_second=0.08,  # match workout_agent_v1's gemini-3.1-pro-preview free-tier pacing
    check_every_n_seconds=0.1,
    max_bucket_size=1,
)

llm = ChatGoogleGenerativeAI(
    model="gemini-3.1-pro-preview",
    temperature=0.1,
    max_retries=2,
    rate_limiter=rate_limiter,
)

_prompt_template = Template(PREPROCESSOR_SYSTEM_PROMPT_TEMPLATE)
SYSTEM_PROMPT = _prompt_template.substitute(
    schema_reference=json.dumps(SAMPLE_USER_PROFILE_V1, indent=2),
)


def _strip_code_fences(text: str) -> str:
    return text.replace("```json", "").replace("```", "").strip()


def generate_user_profile(raw_text: str) -> Dict[str, Any]:
    """Turn free-form client text into a structured profile matching SAMPLE_USER_PROFILE_V1.

    The prompt forbids the model from inventing `user_id`, so it always comes
    back as null; a real id is assigned here rather than left to the LLM to
    avoid a hallucinated identifier.
    """
    agent = create_agent(model=llm, system_prompt=SYSTEM_PROMPT)
    agent_response = agent.invoke({"messages": [HumanMessage(content=raw_text)]})
    raw_json = agent_response["messages"][-1].content

    try:
        profile = json.loads(_strip_code_fences(raw_json))
    except json.JSONDecodeError as e:
        raise ValueError(f"Preprocessor agent returned invalid JSON: {e}\n{raw_json}") from e

    if not profile.get("user_id"):
        profile["user_id"] = f"usr_{uuid.uuid4().hex[:8]}"

    return profile


def generate_workout_plan_from_text(raw_text: str) -> Dict[str, Any]:
    """Full pipeline: raw client text -> structured profile -> workout plan."""
    user_profile = generate_user_profile(raw_text)
    return generate_workout_plan_v1(user_profile)


SAMPLE_RAW_TEXT = """52-year-old woman, 165cm, about 72kg. Wants to improve mobility, and would also like
to lose some weight and get stronger over the next 3 months or so. She's mostly
sedentary these days, has done a little walking and occasional yoga but no real
training experience. Cleared by her doctor for exercise. She has moderate osteoarthritis
in her right knee - pain on deep flexion, so no deep squats. Old left rotator cuff
strain from 2021 that healed but left arm has limited range overhead, so avoid overhead
pressing on that side. Knee and lower back both flare up sometimes. On a beta blocker
and has high blood pressure. Can train 3 days a week, about 30 minutes, mornings,
prefers Monday/Wednesday/Friday. Home only - has light dumbbells, resistance bands and
a chair, no barbell or machines. Likes walking and swimming, hates running and burpees.
Wants an encouraging coaching tone. Resting heart rate around 78, blood pressure 132/85.
Limited hip mobility, no balance issues. Sleep's been poor, stress moderate. Prefers
seated or low-impact options if her knee flares up."""


if __name__ == "__main__":
    print("--- RUNNING PREPROCESSOR ---")
    profile = generate_user_profile(SAMPLE_RAW_TEXT)
    print(json.dumps(profile, indent=2))

    print("\n--- GENERATING WORKOUT PLAN FROM EXTRACTED PROFILE ---")
    plan = generate_workout_plan_v1(profile)
    print(json.dumps(plan, indent=2))
