"""Dry run of the AI Coach agent on one scheduled session: prints the full
prompt, the raw response and the validated suggestions. Nothing is stored
and nothing about the workout changes.

Run (from the repo root):
    .venv/bin/python -m backend.coach_agent.dry_run --user-id 9715424567   # her next scheduled workout
    .venv/bin/python -m backend.coach_agent.dry_run --session-id 84
"""
import argparse
import json
import sys

from ai_usage import set_feature_prefix
from backend.coach_agent import agent
from backend.coach_agent.context import build_context
from backend.coach_agent.prompts import COACH_AGENT_SYSTEM_PROMPT
from backend.coach_agent.repository import CoachAgentRepository
from backend.coach_agent.validate import validate_suggestions
from backend.repository.workout_plan_repository import WorkoutPlanRepository, app_today

RULE = "=" * 100


def _section(title: str) -> None:
    print(f"\n{RULE}\n{title}\n{RULE}", flush=True)


def _next_scheduled_session(repo: CoachAgentRepository, user_id: str):
    rows = (
        repo.client.table("sessions")
        .select("id, scheduled_date, kind, plans!inner(user_id, completed)")
        .eq("plans.user_id", user_id)
        .eq("plans.completed", False)
        .is_("completed_at", "null")
        .gte("scheduled_date", app_today().isoformat())
        .order("scheduled_date")
        .execute()
        .data
    )
    rows = [row for row in rows if row.get("kind") != "cardio"]
    return rows[0]["id"] if rows else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--user-id")
    target.add_argument("--session-id", type=int)
    args = parser.parse_args()

    # Recorded in ai_usage like any call, but tagged as a dry run.
    set_feature_prefix("dry_run_")
    repo = CoachAgentRepository(WorkoutPlanRepository().client)
    session_id = args.session_id or _next_scheduled_session(repo, args.user_id)
    if session_id is None:
        sys.exit(f"No upcoming strength workout for user {args.user_id}")
    session = repo.get_session(session_id)
    if session is None:
        sys.exit(f"No session {session_id}")

    context, facts = build_context(repo, session)
    _section(f"PROMPT — session {session_id} (model={agent.MODEL}, effort={agent.EFFORT})")
    print("--- system ---")
    print(COACH_AGENT_SYSTEM_PROMPT)
    print("--- user ---")
    print(agent.user_content(context))

    result = agent.suggest(context, user_id=facts["user_id"])
    _section("RESPONSE (raw structured output)")
    print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))

    _section("VALIDATED SUGGESTIONS (NOT stored)")
    for row in validate_suggestions(result.exercises, facts):
        before = row["before"]
        print(f"\n[{row['action'].upper()} / {row['status']}] {before['name']}: {before['sets']} x {before['reps']}")
        if row["action"] not in ("keep", "skip"):
            target_id = row["proposed_exercise_id"]
            name = before["name"]
            if target_id:
                for direction in ("progression", "regression"):
                    option = facts["exercises"][row["session_exercise_id"]]["options"][direction].get(target_id)
                    if option:
                        name = option["name"]
            print(f"   -> {name}: {row['proposed_sets']} x {row['proposed_reps']}")
        print(f"   reason: {row['reason']}")
        for item in row["evidence"]:
            mark = "✓" if item["verified"] else "data"
            print(f"   evidence [{item['source']}, {mark}, session {item['session_id']}]: {item['quote']}")


if __name__ == "__main__":
    main()
