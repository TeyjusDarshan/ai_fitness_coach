"""Coach-facing client monitor for the PWA's /admin "Monitor clients" tab.

Lists clients and, for one client, their profile basics, reported joint
pain, period days, app sign-in status, and every past and scheduled workout
(see WorkoutPlanRepository.get_user_workout_history) — read-only. The one
write is the coach editing an upcoming workout's sets and reps. The client's
recorded voice feedback is fetched separately, per session, through
GET /api/admin/sessions/<id>/feedback-audio (backend/app.py).
"""
import logging

from flask import Blueprint, jsonify, request

from backend.auth import auth_repo, require_admin
from backend.repository.workout_plan_repository import WorkoutPlanRepository, app_today, workout_status

logger = logging.getLogger(__name__)

admin_monitor_bp = Blueprint("admin_monitor", __name__)

plan_repo = WorkoutPlanRepository()

# Bounds on a coach-edited prescription. Targets are reps, or seconds for a
# timed exercise, hence the generous ceiling.
MAX_SETS = 10
MAX_TARGET = 600


def _profile_basics(profile):
    """The few profile fields the coach scans first, from the generated
    profile JSON (agents/mock_data_v1.py shape); missing ones are None."""
    profile = profile or {}
    demographics = profile.get("demographics") or {}
    goals = profile.get("goals") or {}
    experience = profile.get("experience") or {}
    availability = profile.get("availability") or {}
    return {
        "age": demographics.get("age"),
        "sex": demographics.get("sex"),
        "primary_goal": goals.get("primary_goal"),
        "experience_level": experience.get("training_experience_level"),
        "days_per_week": availability.get("days_per_week"),
    }


@admin_monitor_bp.get("/api/admin/users")
@require_admin
def list_clients():
    try:
        profiles = plan_repo.list_user_profiles()
        passkeys = auth_repo.passkey_summary()
    except Exception:
        logger.exception("Failed to list clients")
        return jsonify({"error": "Failed to load clients."}), 500
    return jsonify([
        {
            "user_id": row["user_id"],
            "name": row.get("name"),
            "gender": row.get("gender"),
            "updated_at": row.get("updated_at"),
            "has_passkey": row["user_id"] in passkeys,
        }
        for row in profiles
    ]), 200


@admin_monitor_bp.get("/api/admin/users/<user_id>/monitor")
@require_admin
def client_monitor(user_id):
    try:
        row = plan_repo.get_user_profile_row(user_id)
        if row is None:
            return jsonify({"error": f"No client with id {user_id}."}), 404
        sign_in = auth_repo.passkey_summary(user_id).get(user_id, {"passkeys": 0, "last_used_at": None})
        client = {
            "user_id": row["user_id"],
            "name": row.get("name"),
            "gender": row.get("gender"),
            "profile": _profile_basics(row.get("profile")),
            "joint_pain": plan_repo.list_joint_pain(user_id),
            "period_days": plan_repo.list_period_days(user_id),
            "sign_in": sign_in,
        }
        workouts = plan_repo.get_user_workout_history(user_id)
    except Exception:
        logger.exception("Failed to load monitor for user_id=%s", user_id)
        return jsonify({"error": "Failed to load this client."}), 500
    return jsonify({"client": client, "workouts": workouts}), 200


def _is_count(value, upper):
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= upper


@admin_monitor_bp.patch("/api/admin/session-exercises/<int:session_exercise_id>")
@require_admin
def edit_prescription(session_exercise_id):
    """Change an upcoming workout's sets and per-set targets for one
    exercise: `{"sets": 3, "reps": [12, 12, 10]}` (one target per set; reps,
    or seconds for a timed exercise). Only while the workout is still
    scheduled and none of this exercise's sets are logged. Stored like
    progression writes it: one number when every set matches, else a
    comma-separated per-set list. Becomes the baseline next week's
    progression starts from."""
    body = request.get_json(silent=True) or {}
    sets, reps = body.get("sets"), body.get("reps")
    if not _is_count(sets, MAX_SETS):
        return jsonify({"error": f"'sets' must be a whole number from 1 to {MAX_SETS}."}), 400
    if not isinstance(reps, list) or len(reps) != sets or not all(_is_count(r, MAX_TARGET) for r in reps):
        return jsonify({"error": f"'reps' must list one target (1-{MAX_TARGET}) per set."}), 400

    row = plan_repo.get_session_exercise_for_edit(session_exercise_id)
    if row is None:
        return jsonify({"error": f"Exercise slot {session_exercise_id} not found."}), 404
    session = row.get("sessions") or {}
    plan = session.get("plans") or {}
    status, _ = workout_status(session, app_today(), plan_closed=bool(plan.get("completed")))
    if status != "scheduled":
        return jsonify({"error": f"Only upcoming workouts can be edited (this one is {status})."}), 409
    if row.get("session_exercise_set_logs"):
        return jsonify({"error": "She has already logged sets for this exercise."}), 409

    stored = str(reps[0]) if len(set(reps)) == 1 else ",".join(str(r) for r in reps)
    try:
        plan_repo.update_session_exercise_prescription(session_exercise_id, sets, stored)
    except Exception:
        logger.exception("Failed to edit session_exercise_id=%s", session_exercise_id)
        return jsonify({"error": "Failed to save the change."}), 500
    return jsonify({"id": session_exercise_id, "sets": sets, "reps": stored}), 200
