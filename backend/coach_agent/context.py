"""Builds what the AI Coach agent sees for one scheduled session (the JSON
`context`) and the `facts` the validator checks its suggestions against
(current prescriptions, rep bounds, allowed swap targets) — both from the
database, never from the model."""
from typing import Any, Dict, List, Optional, Tuple

from agents.prompts_v1 import DAY_TEMPLATES
from backend.coach_agent.repository import CoachAgentRepository

RPE_LABELS = {6: "too easy", 8: "about right", 10: "too hard"}


def parse_reps(reps: Any, sets: Optional[int]) -> List[int]:
    """A stored `reps` ("12", or per set "12,10,10") as one target per set."""
    sets = sets or 0
    parts = [int(part) for part in str(reps or "").split(",") if part.strip().isdigit()]
    if not parts:
        return []
    if len(parts) == 1:
        return parts * sets if sets else parts
    return parts


def _loaded_joints(exercise: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {"joint": link["joints"]["name"], "load": link.get("joint_load")}
        for link in exercise.get("exercise_loaded_joints") or []
        if link.get("joints")
    ]


def _option(exercise: Dict[str, Any], reason: Optional[str]) -> Dict[str, Any]:
    return {
        "exercise_id": exercise["id"],
        "name": exercise["name"],
        "unit": "seconds" if exercise.get("is_time_based") else "reps",
        "min": exercise.get("min_reps"),
        "max": exercise.get("max_reps"),
        "loaded_joints": _loaded_joints(exercise),
        "avoid_if": exercise.get("avoid_if") or None,
        "edge_reason": reason or None,
    }


def _logged(row: Dict[str, Any]) -> List[int]:
    return [
        log["completed_reps"]
        for log in sorted(row.get("session_exercise_set_logs") or [], key=lambda log: log["set_number"])
    ]


def _history_entry(session: Dict[str, Any]) -> Dict[str, Any]:
    rows = sorted(session.get("session_exercises") or [], key=lambda row: row["id"])
    return {
        "session_id": session["id"],
        "date": (session.get("completed_at") or "")[:10] or session.get("scheduled_date"),
        "status": "completed" if session.get("completed_at") else "missed",
        "on_period": bool(session.get("is_period")),
        "exercises": [
            {
                "name": (row.get("exercises") or {}).get("name"),
                "unit": "seconds" if (row.get("exercises") or {}).get("is_time_based") else "reps",
                "skipped_by_coach": bool(row.get("skipped")),
                "prescribed_sets": row.get("sets"),
                "prescribed_reps": parse_reps(row.get("reps"), row.get("sets")),
                "logged_reps_per_set": _logged(row),
                "rpe": (row.get("session_exercise_rpe") or {}).get("rpe"),
                "felt": RPE_LABELS.get((row.get("session_exercise_rpe") or {}).get("rpe")),
            }
            for row in rows
        ],
    }


def build_context(repo: CoachAgentRepository, session: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """(context for the prompt, facts for validation) for a session row from
    CoachAgentRepository.get_session."""
    plan = session.get("plans") or {}
    user_id = plan["user_id"]
    rows = sorted(
        session.get("session_exercises") or [],
        key=lambda row: (row.get("category") != "primary", row["id"]),
    )

    edges = repo.get_exercise_edges([row["exercise_id"] for row in rows])
    options: Dict[int, Dict[str, List[Dict[str, Any]]]] = {}
    for edge in edges:
        target = edge.get("exercises")
        if not target:
            continue
        options.setdefault(edge["from_exercise_id"], {"progression": [], "regression": []})
        options[edge["from_exercise_id"]].setdefault(edge["type"], []).append(_option(target, edge.get("reason")))

    exercises, facts_by_id = [], {}
    for row in rows:
        exercise = row.get("exercises") or {}
        reps = parse_reps(row.get("reps"), row.get("sets"))
        locked = bool(row.get("session_exercise_set_logs"))
        skipped = bool(row.get("skipped"))
        own_options = options.get(row["exercise_id"], {"progression": [], "regression": []})
        exercises.append({
            "session_exercise_id": row["id"],
            "name": exercise.get("name"),
            "slot": row.get("slot_label"),
            "category": row.get("category"),
            "movement_type": (exercise.get("movement_types") or {}).get("name"),
            "unit": "seconds" if exercise.get("is_time_based") else "reps",
            "min": exercise.get("min_reps"),
            "max": exercise.get("max_reps"),
            "prescribed_sets": row.get("sets"),
            "prescribed_reps": reps,
            "coach_note": row.get("note"),
            "loaded_joints": _loaded_joints(exercise),
            "avoid_if": exercise.get("avoid_if") or None,
            "progression_options": own_options.get("progression", []),
            "regression_options": own_options.get("regression", []),
            "status": "skipped" if skipped else "locked" if locked else "open",
        })
        facts_by_id[row["id"]] = {
            "session_exercise_id": row["id"],
            "exercise_id": row["exercise_id"],
            "name": exercise.get("name"),
            "is_time_based": bool(exercise.get("is_time_based")),
            "sets": row.get("sets"),
            "reps": reps,
            "reps_stored": row.get("reps"),
            "min": exercise.get("min_reps"),
            "max": exercise.get("max_reps"),
            "actionable": not locked and not skipped,
            "options": {
                direction: {option["exercise_id"]: option for option in own_options.get(direction, [])}
                for direction in ("progression", "regression")
            },
        }

    client = repo.get_client(user_id)
    profile_row = client["profile_row"]
    history = [_history_entry(s) for s in repo.get_same_day_history(plan.get("parent_plan_id"), session["day_number"])]
    questions = repo.get_question_history(user_id, session["id"])
    comments = repo.get_recent_comments(user_id)
    split_names = {
        day["day_number"]: day["split_name"]
        for day in DAY_TEMPLATES.get(plan.get("plan_type"), {}).get("schedule", [])
    }

    context = {
        "client": {
            "name": profile_row.get("name"),
            "gender": profile_row.get("gender"),
            "profile": profile_row.get("profile"),
            "joint_pain": client["joint_pain"],
            "recent_period_days": client["period_days"],
            "coach_notes_this_week": plan.get("coach_notes"),
            "safety_summary": plan.get("safety_summary"),
        },
        "session": {
            "session_id": session["id"],
            "scheduled_date": session.get("scheduled_date"),
            "day_number": session["day_number"],
            "split_name": split_names.get(session["day_number"]),
        },
        "exercises": exercises,
        "same_day_last_two_weeks": history,
        "previous_questions_and_answers": questions,
        "recent_client_comments": comments,
    }

    # Texts the client's quoted evidence must come from.
    client_texts = [
        q["answer"] for entry in questions for q in entry["questions"] if q.get("answer")
    ] + [c["quote"] for c in comments if c.get("quote")] + [c["comment"] for c in comments if c.get("comment")]
    facts = {"user_id": user_id, "exercises": facts_by_id, "client_texts": client_texts}
    return context, facts
