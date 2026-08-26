"""Flask API for the raw-text -> profile -> workout-plan pipeline.

Run (from the repo root):  python3 -m backend.app   then:

  curl -X POST http://localhost:8001/api/workout-plan \\
    -H "Content-Type: application/json" \\
    -d '{"userid": "usr_10235", "raw_user_text": "..."}'
"""
import time

from flask import Flask, jsonify, request

from agents.preprocessor_agent import generate_user_profile
from agents.workout_agent import generate_workout_plan_v1
from backend.kafka_producer import KafkaProducerClient
from backend.repository.workout_plan_repository import PainLevel, WorkoutPlanRepository

app = Flask(__name__)
plan_repo = WorkoutPlanRepository()
kafka_producer = KafkaProducerClient()


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


@app.post("/api/workout-plan")
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


@app.patch("/api/workout-plan/<int:session_id>/complete")
def complete_session(session_id):
    try:
        updated = plan_repo.mark_session_completed(session_id)
    except Exception:
        app.logger.exception("Failed to mark session_id=%s completed", session_id)
        return jsonify({"error": "Failed to mark workout as completed."}), 500

    if updated is None:
        return jsonify({"error": f"Session {session_id} not found."}), 404
    return jsonify(updated), 200


@app.post("/api/users/<user_id>/progress-plan")
def progress_plan(user_id):
    existing = plan_repo.get_unfinished_session(user_id)
    if existing is not None:
        response = dict(existing["plan"])
        response["session_id"] = existing["id"]
        response["completed"] = existing["completed"]
        return jsonify(response), 200

    last = plan_repo.get_last_completed_session(user_id)
    if last is None:
        return jsonify({"error": f"No completed session found for user_id={user_id}."}), 404

    try:
        plan_repo.create_progressed_session(user_id, last["session"], last["exercise_rows"])
    except Exception:
        app.logger.exception("Failed to create progressed session for user_id=%s", user_id)
        return jsonify({"error": "Failed to create the next session."}), 500

    new_plan = plan_repo.get_unfinished_session(user_id)
    response = dict(new_plan["plan"])
    response["session_id"] = new_plan["id"]
    response["completed"] = new_plan["completed"]
    return jsonify(response), 200


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


@app.post("/api/users/<user_id>/joint-pain")
def update_joint_pain(user_id):
    if not plan_repo.user_exists(user_id):
        return jsonify({"error": f"User {user_id} not found."}), 404

    body = request.get_json(silent=True) or {}
    joints = body.get("joints")
    if not isinstance(joints, list) or not joints:
        return jsonify({"error": "'joints' (non-empty list) is required."}), 400

    valid_pain_levels = {level.value for level in PainLevel}
    parsed = []
    for entry in joints:
        joint_id = entry.get("joint_id") if isinstance(entry, dict) else None
        pain_level = entry.get("pain_level") if isinstance(entry, dict) else None
        if (
            not isinstance(joint_id, int)
            or isinstance(joint_id, bool)
            or pain_level not in valid_pain_levels
        ):
            return jsonify({
                "error": "Each entry in 'joints' requires an int 'joint_id' and a 'pain_level' "
                         f"in {sorted(valid_pain_levels)}."
            }), 400
        parsed.append({"joint_id": joint_id, "pain_level": pain_level})

    try:
        updated = plan_repo.upsert_joint_pain(user_id, parsed)
    except Exception:
        app.logger.exception("Failed to update joint pain for user_id=%s", user_id)
        return jsonify({"error": "Failed to update joint pain."}), 500

    return jsonify({"joints": updated}), 200


@app.delete("/api/users/<user_id>/joint-pain/<int:joint_id>")
def delete_joint_pain(user_id, joint_id):
    if not plan_repo.user_exists(user_id):
        return jsonify({"error": f"User {user_id} not found."}), 404

    try:
        deleted = plan_repo.delete_joint_pain(user_id, joint_id)
    except Exception:
        app.logger.exception(
            "Failed to delete joint pain for user_id=%s joint_id=%s", user_id, joint_id
        )
        return jsonify({"error": "Failed to delete joint pain."}), 500

    if not deleted:
        return jsonify({
            "error": f"No joint pain reported for user_id={user_id}, joint_id={joint_id}."
        }), 404
    return jsonify({"user_id": user_id, "joint_id": joint_id, "deleted": True}), 200


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


@app.patch("/api/sessions/<int:session_id>/exercises/<int:session_exercise_id>/sets/<int:set_number>")
def log_set(session_id, session_exercise_id, set_number):
    body = request.get_json(silent=True) or {}
    completed_reps = body.get("completed_reps")
    if not isinstance(completed_reps, int) or isinstance(completed_reps, bool) or completed_reps < 0:
        return jsonify({"error": "'completed_reps' (non-negative int) is required."}), 400

    try:
        log = plan_repo.log_set(session_id, session_exercise_id, set_number, completed_reps)
    except Exception:
        app.logger.exception(
            "Failed to log set_number=%s for session_exercise_id=%s", set_number, session_exercise_id
        )
        return jsonify({"error": "Failed to log this set."}), 500

    if log is None:
        return jsonify({"error": "Exercise not found in this session, or set_number out of range."}), 404
    return jsonify(log), 200


@app.patch("/api/sessions/<int:session_id>/exercises/<int:session_exercise_id>/rpe")
def log_rpe(session_id, session_exercise_id):
    body = request.get_json(silent=True) or {}
    rpe = body.get("rpe")
    if not isinstance(rpe, int) or isinstance(rpe, bool) or not (1 <= rpe <= 10):
        return jsonify({"error": "'rpe' (int 1-10) is required."}), 400

    try:
        log = plan_repo.log_rpe(session_id, session_exercise_id, rpe)
    except Exception:
        app.logger.exception("Failed to log rpe for session_exercise_id=%s", session_exercise_id)
        return jsonify({"error": "Failed to log RPE."}), 500

    if log is None:
        return jsonify({"error": "Exercise not found in this session."}), 404
    return jsonify(log), 200


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

    try:
        kafka_producer.send_workout_complete_event(session_id, day_number)
    except Exception:
        # Day completion already succeeded in the DB; a failure to publish
        # this notification shouldn't fail the request.
        app.logger.exception(
            "Failed to publish workout-complete event for session_id=%s day_number=%s",
            session_id, day_number,
        )

    return jsonify(summary), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001, debug=True)
