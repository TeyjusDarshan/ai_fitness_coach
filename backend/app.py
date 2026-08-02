"""Flask API for the raw-text -> profile -> workout-plan pipeline.

Run (from the repo root):  python3 -m backend.app   then:

  curl -X POST http://localhost:8001/workout-plan \\
    -H "Content-Type: application/json" \\
    -d '{"userid": "usr_10235", "raw_user_text": "..."}'
"""
import os
import time

from flask import Flask, abort, jsonify, request, send_from_directory

from agents.preprocessor_agent import generate_user_profile
from agents.workout_agent import generate_workout_plan_v1
from backend.repository.workout_plan_repository import WorkoutPlanRepository

FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")

# static_folder=None: Flask's automatic static route registers at the same
# "/<path:...>" pattern as our SPA catch-all below and wins by registration
# order, shadowing it. Serve frontend/dist entirely through the catch-all below.
app = Flask(__name__, static_folder=None)
plan_repo = WorkoutPlanRepository()


def _persist_generated_session(user_id, profile, plan, max_attempts=2):
    """Upsert the profile and insert the new session, retrying once on failure.

    Both calls are safe to repeat: the profile upsert overwrites, and a
    session row from a failed attempt was never committed, so retrying
    doesn't create duplicates.
    """
    last_exc = None
    for attempt in range(max_attempts):
        try:
            plan_repo.upsert_user_profile(user_id, profile)
            return plan_repo.create_session(user_id, plan)
        except Exception as e:
            last_exc = e
            if attempt < max_attempts - 1:
                time.sleep(0.5)
    raise last_exc


@app.post("/workout-plan")
def create_workout_plan():
    body = request.get_json(silent=True) or {}
    user_id = body.get("userid")
    raw_user_text = body.get("raw_user_text")

    if not user_id or not raw_user_text:
        return jsonify({"error": "Both 'userid' and 'raw_user_text' are required."}), 400

    existing = plan_repo.get_unfinished_session(user_id)
    if existing is not None:
        response = dict(existing["plan"])
        response["session_id"] = existing["id"]
        response["completed"] = existing["completed"]
        return jsonify(response), 200

    try:
        profile = generate_user_profile(raw_user_text)
    except ValueError as e:
        return jsonify({"error": f"Failed to extract client profile: {e}"}), 502

    # The preprocessor assigns its own placeholder user_id (it's forbidden
    # from inventing one) — the caller's id is authoritative.
    profile["user_id"] = user_id

    plan = generate_workout_plan_v1(profile)
    if "error" in plan:
        return jsonify(plan), 500

    try:
        session_row = _persist_generated_session(user_id, profile, plan)
    except Exception:
        app.logger.exception("Failed to persist generated session for user_id=%s", user_id)
        return jsonify({"error": "Failed to save generated workout after retrying."}), 500

    response = dict(plan)
    response["session_id"] = session_row["id"]
    response["completed"] = session_row["completed"]
    return jsonify(response), 200


@app.patch("/workout-plan/<int:session_id>/complete")
def complete_session(session_id):
    try:
        updated = plan_repo.mark_session_completed(session_id)
    except Exception:
        app.logger.exception("Failed to mark session_id=%s completed", session_id)
        return jsonify({"error": "Failed to mark workout as completed."}), 500

    if updated is None:
        return jsonify({"error": f"Session {session_id} not found."}), 404
    return jsonify(updated), 200


@app.get("/api/users/<user_id>/dashboard")
def get_dashboard(user_id):
    existing = plan_repo.get_unfinished_session(user_id)
    if existing is None:
        return jsonify({"error": "No plan found for this user."}), 404

    session_id = existing["id"]
    plan = existing["plan"]
    day_logs = plan_repo.list_day_logs(session_id)

    found_next = False
    days = []
    for day in plan["schedule"]:
        log = day_logs.get(day["day_number"], {})
        if day["is_rest_day"]:
            status = "rest"
        elif log.get("completed_at"):
            status = "completed"
        elif not found_next:
            status = "next"
            found_next = True
        else:
            status = "upcoming"
        days.append({
            **day,
            "status": status,
            "started_at": log.get("started_at"),
            "completed_at": log.get("completed_at"),
        })

    profile = plan_repo.get_profile(user_id) or {}
    session_duration_minutes = (profile.get("availability") or {}).get("session_duration_minutes")

    return jsonify({
        "session_id": session_id,
        "plan_type": plan["plan_type"],
        "plan_selection_reason": plan["plan_selection_reason"],
        "medical_clearance_warning": plan["medical_clearance_warning"],
        "coach_notes": plan["coach_notes"],
        "safety_summary": plan["safety_summary"],
        "session_duration_minutes": session_duration_minutes,
        "days": days,
    }), 200


@app.post("/api/sessions/<int:session_id>/days/<int:day_number>/start")
def start_day(session_id, day_number):
    try:
        log = plan_repo.start_day(session_id, day_number)
    except Exception:
        app.logger.exception(
            "Failed to start day_number=%s for session_id=%s", day_number, session_id
        )
        return jsonify({"error": "Failed to start this day."}), 500
    return jsonify(log), 200


@app.patch("/api/sessions/<int:session_id>/exercises/<int:session_exercise_id>/sets/<int:set_index>")
def toggle_set(session_id, session_exercise_id, set_index):
    body = request.get_json(silent=True) or {}
    completed = body.get("completed")
    if not isinstance(completed, bool):
        return jsonify({"error": "'completed' (bool) is required."}), 400

    try:
        completed_sets = plan_repo.set_completed(session_id, session_exercise_id, set_index, completed)
    except Exception:
        app.logger.exception(
            "Failed to toggle set_index=%s for session_exercise_id=%s", set_index, session_exercise_id
        )
        return jsonify({"error": "Failed to update this set."}), 500

    if completed_sets is None:
        return jsonify({"error": "Exercise not found in this session, or set_index out of range."}), 404
    return jsonify({"completed_sets": completed_sets}), 200


@app.post("/api/sessions/<int:session_id>/days/<int:day_number>/complete")
def complete_day(session_id, day_number):
    try:
        summary = plan_repo.complete_day(session_id, day_number)
    except Exception:
        app.logger.exception(
            "Failed to complete day_number=%s for session_id=%s", day_number, session_id
        )
        return jsonify({"error": "Failed to complete this day."}), 500

    if summary is None:
        return jsonify({"error": f"Session {session_id} not found."}), 404
    return jsonify(summary), 200


@app.get("/", defaults={"path": ""})
@app.get("/<path:path>")
def spa(path):
    if path.startswith("api/"):
        abort(404)
    full_path = os.path.join(FRONTEND_DIST, path)
    if path and os.path.isfile(full_path):
        return send_from_directory(FRONTEND_DIST, path)
    return send_from_directory(FRONTEND_DIST, "index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001, debug=True)
