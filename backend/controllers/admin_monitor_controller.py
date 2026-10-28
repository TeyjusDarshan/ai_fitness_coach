"""Coach-facing client monitor for the PWA's /admin "Monitor clients" tab.

Read-only: lists clients and, for one client, their profile basics, reported
joint pain, period days, app sign-in status, and every past and scheduled
workout (see WorkoutPlanRepository.get_user_workout_history). The client's
recorded voice feedback is fetched separately, per session, through
GET /api/admin/sessions/<id>/feedback-audio (backend/app.py).
"""
import logging

from flask import Blueprint, jsonify

from backend.auth import auth_repo, require_admin
from backend.repository.workout_plan_repository import WorkoutPlanRepository

logger = logging.getLogger(__name__)

admin_monitor_bp = Blueprint("admin_monitor", __name__)

plan_repo = WorkoutPlanRepository()


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
