"""AI Coach suggestions for the PWA's /admin "Monitor clients" tab.

The coach asks for suggestions on one scheduled strength workout; the AI
Coach agent (backend/coach_agent) reviews everything known about the client
and proposes, per exercise, to keep it, adjust its sets/reps, move it to its
progression or regression, or skip it for that workout — each with a reason
and quoted evidence. The coach accepts or rejects each suggestion; accepting
applies it the same way the coach's own prescription edit does.
"""
import logging
from typing import Any, Dict, List

from flask import Blueprint, jsonify

from backend.auth import require_admin
from backend.coach_agent import agent
from backend.coach_agent.context import build_context
from backend.coach_agent.repository import CoachAgentRepository
from backend.coach_agent.validate import validate_suggestions
from backend.controllers.admin_monitor_controller import _swapped_exercise, exercise_repo, plan_repo
from backend.repository.workout_plan_repository import app_today, workout_status

logger = logging.getLogger(__name__)

admin_coach_agent_bp = Blueprint("admin_coach_agent", __name__)

coach_repo = CoachAgentRepository(plan_repo.client)


def _range(exercise: Dict[str, Any]) -> Any:
    low, high = exercise.get("min_reps"), exercise.get("max_reps")
    return f"{low}-{high}" if low is not None and high is not None else None


def _shape(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """exercise_suggestions rows -> what the admin screen shows: current vs
    proposed (with exercise names and rep ranges), reason, evidence."""
    exercises = coach_repo.get_exercises(
        [row["before"]["exercise_id"] for row in rows]
        + [row["proposed_exercise_id"] for row in rows if row.get("proposed_exercise_id")]
    )
    shaped = []
    for row in rows:
        before = row["before"]
        current = exercises.get(before["exercise_id"], {})
        proposed_exercise = exercises.get(row.get("proposed_exercise_id")) or current
        shaped.append({
            "id": row["id"],
            "session_exercise_id": row["session_exercise_id"],
            "action": row["action"],
            "status": row["status"],
            "reason": row["reason"],
            "evidence": row.get("evidence") or [],
            "current": {
                "exercise_id": before["exercise_id"],
                "name": before.get("name") or current.get("name"),
                "sets": before.get("sets"),
                "reps": before.get("reps"),
                "rep_range": _range(current),
                "is_time_based": bool(current.get("is_time_based")),
            },
            "proposed": None if row["action"] in ("keep", "skip") else {
                "exercise_id": proposed_exercise.get("id"),
                "name": proposed_exercise.get("name"),
                "sets": row.get("proposed_sets"),
                "reps": row.get("proposed_reps"),
                "rep_range": _range(proposed_exercise),
                "is_time_based": bool(proposed_exercise.get("is_time_based")),
            },
        })
    return shaped


def _run_payload(run: Dict[str, Any]) -> Dict[str, Any]:
    rows = sorted(run.get("exercise_suggestions") or [], key=lambda row: row["id"])
    return {
        "run": {"id": run["id"], "overview": run.get("overview"), "model": run.get("model"),
                "created_at": run.get("created_at")},
        "suggestions": _shape(rows),
    }


def _session_status(session: Dict[str, Any]) -> str:
    plan = session.get("plans") or {}
    status, _ = workout_status(session, app_today(), plan_closed=bool(plan.get("completed")))
    return status


@admin_coach_agent_bp.post("/api/admin/sessions/<int:session_id>/suggestions")
@require_admin
def create_suggestions(session_id):
    """Run the AI Coach on a scheduled strength workout and store its
    suggestions (replacing any still pending from an earlier run)."""
    session = coach_repo.get_session(session_id)
    if session is None:
        return jsonify({"error": f"Workout {session_id} not found."}), 404
    if session.get("kind") == "cardio":
        return jsonify({"error": "The AI coach only reviews strength workouts."}), 409
    status = _session_status(session)
    if status != "scheduled":
        return jsonify({"error": f"Only upcoming workouts can be reviewed (this one is {status})."}), 409

    try:
        context, facts = build_context(coach_repo, session)
    except Exception:
        logger.exception("Failed to build AI coach context for session_id=%s", session_id)
        return jsonify({"error": "Failed to load this workout's details."}), 500
    if not any(ex["actionable"] for ex in facts["exercises"].values()):
        return jsonify({"error": "Nothing in this workout can be changed."}), 409

    try:
        result = agent.suggest(context)
    except Exception:
        logger.exception("AI coach failed for session_id=%s", session_id)
        return jsonify({"error": "The AI coach couldn't finish. Try again."}), 502

    rows = validate_suggestions(result.exercises, facts)
    try:
        run = coach_repo.save_run(session_id, facts["user_id"], result.overview.strip(), agent.MODEL, rows)
    except Exception:
        logger.exception("Failed to store AI coach suggestions for session_id=%s", session_id)
        return jsonify({"error": "Failed to save the suggestions."}), 500
    return jsonify(_run_payload(run)), 200


@admin_coach_agent_bp.get("/api/admin/sessions/<int:session_id>/suggestions")
@require_admin
def latest_suggestions(session_id):
    try:
        run = coach_repo.get_latest_run(session_id)
    except Exception:
        logger.exception("Failed to load AI coach suggestions for session_id=%s", session_id)
        return jsonify({"error": "Failed to load the suggestions."}), 500
    if run is None:
        return jsonify({"run": None, "suggestions": []}), 200
    return jsonify(_run_payload(run)), 200


@admin_coach_agent_bp.post("/api/admin/exercise-suggestions/<int:suggestion_id>/accept")
@require_admin
def accept_suggestion(suggestion_id):
    """Apply one pending suggestion — re-checked against the workout as it
    is now — and return the exercise's new fields for the admin card."""
    suggestion = coach_repo.get_suggestion(suggestion_id)
    if suggestion is None:
        return jsonify({"error": f"Suggestion {suggestion_id} not found."}), 404
    if suggestion["status"] != "pending":
        return jsonify({"error": f"This suggestion is already {suggestion['status']}."}), 409

    row = plan_repo.get_session_exercise_for_edit(suggestion["session_exercise_id"])
    if row is None:
        return jsonify({"error": "That exercise no longer exists."}), 409
    status = _session_status(row.get("sessions") or {})
    if status != "scheduled":
        return jsonify({"error": f"Only upcoming workouts can be changed (this one is {status})."}), 409
    if row.get("session_exercise_set_logs"):
        return jsonify({"error": "She has already logged sets for this exercise."}), 409
    before = suggestion["before"]
    if (
        row.get("skipped")
        or row.get("exercise_id") != before.get("exercise_id")
        or row.get("sets") != before.get("sets")
        or str(row.get("reps")) != str(before.get("reps"))
    ):
        return jsonify({"error": "This exercise was changed after the suggestion was made. Ask the AI coach again."}), 409

    action = suggestion["action"]
    session_exercise_id = suggestion["session_exercise_id"]
    exercise_update: Dict[str, Any] = {"id": session_exercise_id}
    try:
        if action == "skip":
            plan_repo.set_session_exercise_skipped(session_exercise_id, True, suggestion["reason"])
            exercise_update.update({"skipped": True, "skip_reason": suggestion["reason"]})
        elif action == "adjust":
            plan_repo.update_session_exercise_prescription(
                session_exercise_id, suggestion["proposed_sets"], suggestion["proposed_reps"]
            )
            exercise_update.update({"sets": suggestion["proposed_sets"], "reps": suggestion["proposed_reps"]})
        elif action in ("progress", "regress"):
            swap = exercise_repo.get_exercise(suggestion["proposed_exercise_id"])
            if swap is None:
                return jsonify({"error": "The suggested exercise no longer exists."}), 409
            plan_repo.update_session_exercise_prescription(
                session_exercise_id, suggestion["proposed_sets"], suggestion["proposed_reps"], exercise=swap
            )
            exercise_update.update({
                "sets": suggestion["proposed_sets"],
                "reps": suggestion["proposed_reps"],
                "exercise": _swapped_exercise(swap),
            })
        else:
            return jsonify({"error": "This suggestion makes no change."}), 409
        coach_repo.set_suggestion_status(suggestion_id, "accepted")
    except Exception:
        logger.exception("Failed to apply suggestion_id=%s", suggestion_id)
        return jsonify({"error": "Failed to apply the suggestion."}), 500
    return jsonify({"id": suggestion_id, "status": "accepted", "exercise": exercise_update}), 200


@admin_coach_agent_bp.post("/api/admin/exercise-suggestions/<int:suggestion_id>/reject")
@require_admin
def reject_suggestion(suggestion_id):
    suggestion = coach_repo.get_suggestion(suggestion_id)
    if suggestion is None:
        return jsonify({"error": f"Suggestion {suggestion_id} not found."}), 404
    if suggestion["status"] != "pending":
        return jsonify({"error": f"This suggestion is already {suggestion['status']}."}), 409
    try:
        coach_repo.set_suggestion_status(suggestion_id, "rejected")
    except Exception:
        logger.exception("Failed to reject suggestion_id=%s", suggestion_id)
        return jsonify({"error": "Failed to reject the suggestion."}), 500
    return jsonify({"id": suggestion_id, "status": "rejected"}), 200
