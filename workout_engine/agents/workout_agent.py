import json
from typing import Any, Dict, List, TypedDict
from string import Template

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_mistralai import ChatMistralAI
from langgraph.graph import END, START, StateGraph

from agents.mock_data import SAMPLE_HEALTHY_MALE_INPUT, SAMPLE_MACRO_PLAN, SAMPLE_HEART_PATIENT_INPUT
from agents.prompts import (
    MACRO_SYSTEM_PROMPT,
    MICRO_SYSTEM_PROMPT_TEMPLATE,
    MICRO_WORKOUT_RESPONSE_FORMAT,
)
from agents.tools.workout_tools import repo, search_exercises

load_dotenv()

llm = ChatMistralAI(
    model="mistral-large-latest",
    temperature=0.1,
    max_retries=2,
)


def _fetch_reference_data() -> str:
    """Fetch the static lookup tables once and format them as compact JSON.

    These tables (movement patterns, muscle groups, equipment, exercise
    types, body parts) rarely change, so we resolve them a single time at
    import and inline them into the system prompt instead of exposing them
    as tools. That removes ~5 extra sequential LLM<->tool round trips per
    micro-workout generation, which is what was blowing through the
    Mistral free-tier rate limit.
    """

    def compact(rows, fields):
        return [{field: row[field] for field in fields} for row in rows]

    reference = {
        "movement_patterns": compact(repo.get_all_movement_patterns(), ["id", "name"]),
        "muscle_groups": compact(repo.get_all_muscle_groups(), ["id", "name", "body_region"]),
        "equipment": compact(repo.get_all_equipment(), ["id", "name", "is_home_friendly"]),
        "exercise_types": compact(repo.get_all_exercise_types(), ["id", "name"]),
        "body_parts": compact(repo.get_all_body_parts(), ["id", "name"]),
    }
    return json.dumps(reference, indent=2)


REFERENCE_DATA = _fetch_reference_data()

prompt_template = Template(MICRO_SYSTEM_PROMPT_TEMPLATE)
SYSTEM_PROMPT = prompt_template.substitute(reference_data=REFERENCE_DATA)


class CoachState(TypedDict):
    # Inputs
    user_profile: Dict[str, Any]

    # Outputs managed by the graph
    macro_plan: List[Dict[str, str]]
    detailed_workouts: Dict[str, Any]
    current_day_idx: int


def _print_tool_calls(messages, max_result_chars: int = 600) -> None:
    """Pretty-print every tool call an agent made, alongside its result.

    `messages` is the full message history returned by `agent.invoke`
    (a mix of Human/AI/Tool messages). AI messages carry the tool calls the
    model decided to make; Tool messages carry the corresponding results,
    linked back via `tool_call_id`.
    """
    results_by_call_id = {
        message.tool_call_id: message.content
        for message in messages
        if isinstance(message, ToolMessage)
    }

    call_count = 0
    for message in messages:
        if not isinstance(message, AIMessage) or not message.tool_calls:
            continue
        for call in message.tool_calls:
            call_count += 1
            args_str = json.dumps(call["args"], indent=2)
            result = str(results_by_call_id.get(call["id"], "<no result>"))
            if len(result) > max_result_chars:
                result = f"{result[:max_result_chars]}... [truncated, {len(result)} chars total]"

            print(f"\n[tool call {call_count}] {call['name']}")
            print(f"  args   : {args_str}")
            print(f"  result : {result}")

    if call_count:
        print(f"\n--- {call_count} tool call(s) total ---\n")


def generate_macro_split_node(state: CoachState):
    """Phase 1: Generates the high-level weekly movement-pattern split."""
    print("--- GENERATING HIGH-LEVEL WEEKLY SPLIT ---")

    agent = create_agent(
        model=llm,
        system_prompt=MACRO_SYSTEM_PROMPT,
    )

    prompt_content = f"{state['user_profile']}"
    agent_response = agent.invoke({"messages": [HumanMessage(content=prompt_content)]})
    raw_text_content = agent_response["messages"][-1].content

    try:
        clean_json_str = raw_text_content.replace("```json", "").replace("```", "").strip()
        result_json = json.loads(clean_json_str)
    except Exception as e:
        print(f"Failed to parse JSON text: {e}")
        result_json = {"schedule": []}

    return {"macro_plan": result_json, "current_day_idx": 0}


def generate_micro_workout_node(state: CoachState):
    """Phase 2: Loops through and generates exercises for a single day at a time."""
    agent = create_agent(
        model=llm,
        tools=[search_exercises],
        system_prompt=SYSTEM_PROMPT,
    )


    idx = state["current_day_idx"]
    day_plan = state["macro_plan"]["schedule"][idx]
    day_name = day_plan["day"]
    day_type = day_plan["type"]
    day_focus = day_plan["target_movement_patterns"]

    print(f"--- GENERATING EXERCISES FOR: {day_name} ({day_focus}) ---")

    # If it's a rest day, we don't need the LLM to write a routine
    if day_type.lower() == "rest":
        updated_workouts = {**state.get("detailed_workouts", {})}
        updated_workouts[day_name] = {"type": "Rest Day", "activities": ["Light walking", "Mobility / Stretching"]}
        return {"detailed_workouts": updated_workouts, "current_day_idx": idx + 1}

    # If it's an active day, prompt the micro agent to write exercises
    prompt_content = f"""
    {state["user_profile"]}

    macro_split: {day_plan}
    """

    agent_response = agent.invoke({"messages": [HumanMessage(content=prompt_content)]})

    _print_tool_calls(agent_response["messages"])

    final_answer = agent_response["messages"][-1].content


    try:
        clean_json = final_answer.replace("```json", "").replace("```", "").strip()
        result_json = json.loads(clean_json)
    except Exception:
        result_json = {"routine": []}

    updated_workouts = {**state.get("detailed_workouts", {})}
    updated_workouts[day_name] = {
        "focus": day_focus,
        "routine": result_json["routine"],
    }

    return {"detailed_workouts": updated_workouts, "current_day_idx": idx + 1}


def check_if_week_completed(state: CoachState):
    """Evaluates whether all days in the macro plan have exercises populated."""
    if state["current_day_idx"] < len(state["macro_plan"]["schedule"]):
        return "generate_next_day"
    return "complete_week"


builder = StateGraph(CoachState)

builder.add_node("macro_planner", generate_macro_split_node)
builder.add_node("micro_planner", generate_micro_workout_node)

builder.add_edge(START, "macro_planner")
builder.add_edge("macro_planner", "micro_planner")

builder.add_conditional_edges(
    "micro_planner",
    check_if_week_completed,
    {
        "generate_next_day": "micro_planner",  # Loop back to generate the next day
        "complete_week": END,  # Exit the graph once all days are populated
    },
)

app = builder.compile()


if __name__ == "__main__":
    coach_state = CoachState(
        user_profile=SAMPLE_HEART_PATIENT_INPUT["client_profile"],
    )
    macro_plan = generate_macro_split_node(coach_state)
    
    print('MACRO_PLAN', macro_plan)

    coach_state = CoachState(
        user_profile=SAMPLE_HEART_PATIENT_INPUT["client_profile"],
        macro_plan=macro_plan['macro_plan'],
        current_day_idx=3,
    )

    micro_plan= generate_micro_workout_node(coach_state)
    print(micro_plan)
