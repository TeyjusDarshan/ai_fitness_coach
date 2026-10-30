"""Flask API for the raw-text -> profile -> workout-plan pipeline.

Run (from the repo root):  python3 -m backend.app   then:

  curl -X POST http://localhost:8001/api/workout-plan \\
    -H "Content-Type: application/json" \\
    -H "X-Admin-Key: $ADMIN_API_KEY" \\
    -d '{"userid": "usr_10235", "raw_user_text": "..."}'

Coach/admin routes require the X-Admin-Key header; the PWA's routes require
a passkey sign-in session (see backend/auth.py and
backend/controllers/auth_controller.py).
"""
import time
from datetime import date, timedelta

from flask import Flask, g, jsonify, request

from agents.preprocessor_agent import generate_user_profile
from agents.workout_agent import generate_workout_plan_v1
from backend.auth import require_admin, require_auth
from backend.feedback_storage import (
    MAX_FEEDBACK_BYTES,
    SIGNED_URL_TTL_SECONDS,
    feedback_path,
    feedback_storage,
)
from backend.controllers.admin_monitor_controller import admin_monitor_bp
from backend.controllers.admin_plan_controller import admin_plan_bp
from backend.controllers.auth_controller import auth_bp
from backend.controllers.whatsapp_webhook_controller import whatsapp_webhook_bp
from backend.repository.workout_plan_repository import (
    PainLevel,
    WorkoutPlanRepository,
    app_today,
    is_session_missed,
    workout_duration_seconds,
    workout_status,
)

app = Flask(__name__)
app.register_blueprint(whatsapp_webhook_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(admin_plan_bp)
app.register_blueprint(admin_monitor_bp)
plan_repo = WorkoutPlanRepository()


def _deny_unless_session_open(session_id):
    """Error response unless the signed-in user owns this session, its
    scheduled_date has arrived, and it wasn't missed (date passed without
    being completed), else None. A completed session stays open, so its
    summary can be re-opened."""
    session = plan_repo.get_session(session_id)
    if session is None:
        return jsonify({"error": f"Session {session_id} not found."}), 404
    if (session.get("plans") or {}).get("user_id") != g.user_id:
        return jsonify({"error": "You don't have access to this session."}), 403
    today = app_today()
    scheduled = date.fromisoformat(session["scheduled_date"])
    if scheduled > today:
        return jsonify({
            "error": f"This workout opens on {scheduled:%a} {scheduled.day} {scheduled:%b}.",
            "scheduled_date": session["scheduled_date"],
        }), 409
    if is_session_missed(session, today):
        return jsonify({
            "error": "This workout was missed.",
            "scheduled_date": session["scheduled_date"],
            "missed": True,
        }), 409
    return None


# How many past (completed or missed) workouts the dashboard shows before the
# upcoming ones, reaching back into the previous plan if need be.
DASHBOARD_PAST_WORKOUTS = 2


def _dashboard_workout(workout, today, plan_closed=False):
    """A _workout_entries entry with its dashboard status and display date.
    An uncompleted workout of an already-closed plan counts as missed even if
    its date hadn't arrived (the coach closed the plan early). is_today marks
    the one the dashboard's Today card shows: completed or scheduled today."""
    status, shown = workout_status(workout, today, plan_closed)
    return {
        **workout,
        "status": status,
        "date": shown,
        "is_today": shown == today.isoformat(),
        "duration_seconds": workout_duration_seconds(workout),
        "is_next": False,
        "can_start": False,
    }


def _dashboard_workouts(user_id, existing, today):
    """The dashboard's workout panels: the last DASHBOARD_PAST_WORKOUTS past
    workouts (from the previous plan too, early in a new one), then every
    workout still scheduled. The first scheduled one is is_next, and only a
    scheduled workout dated today can_start."""
    current = [_dashboard_workout(w, today) for w in existing["workouts"]]
    past = [w for w in current if w["status"] != "scheduled"]
    upcoming = [w for w in current if w["status"] == "scheduled"]
    if len(past) < DASHBOARD_PAST_WORKOUTS:
        previous = [
            _dashboard_workout(w, today, plan_closed=True)
            for w in plan_repo.get_previous_plan_workouts(user_id, existing["id"])
        ]
        past = previous + past
    past = past[-DASHBOARD_PAST_WORKOUTS:]

    for workout in upcoming:
        workout["can_start"] = workout["scheduled_date"] == today.isoformat()
    if upcoming:
        upcoming[0]["is_next"] = True
    return past + upcoming


def _plan_response(existing):
    response = dict(existing["plan"])
    response["plan_id"] = existing["id"]
    response["completed"] = existing["completed"]
    return response


def _persist_generated_plan(user_id, profile, plan, start_date, name=None, max_attempts=2):
    """Upsert the profile and insert the new plan, retrying once on failure.

    Safe to repeat: the profile upsert overwrites, and if a failed attempt
    left a partial plan behind, the retry is refused by the
    one-unfinished-plan-per-user index rather than creating a duplicate.
    """
    last_exc = None
    for attempt in range(max_attempts):
        try:
            plan_repo.upsert_user_profile(user_id, profile, name)
            return plan_repo.create_plan(user_id, plan, start_date)
        except Exception as e:
            last_exc = e
            if attempt < max_attempts - 1:
                time.sleep(0.5)
    raise last_exc


@app.post("/api/workout-plan")
@require_admin
def create_workout_plan():
    body = request.get_json(silent=True) or {}
    user_id = body.get("userid")
    raw_user_text = body.get("raw_user_text")

    if not user_id or not raw_user_text:
        return jsonify({"error": "Both 'userid' and 'raw_user_text' are required."}), 400
    # Optional client display name; left unchanged on an existing user when omitted.
    name = body.get("name")
    if name is not None and (not isinstance(name, str) or not name.strip()):
        return jsonify({"error": "'name' must be a non-empty string."}), 400
    name = name.strip() if name else None

    start_date = app_today()
    if body.get("start_date") is not None:
        try:
            start_date = date.fromisoformat(body["start_date"])
        except (TypeError, ValueError):
            return jsonify({"error": "'start_date' must be a YYYY-MM-DD date."}), 400
        if start_date < app_today():
            return jsonify({"error": "'start_date' can't be in the past."}), 400

    existing = plan_repo.get_unfinished_plan(user_id)
    if existing is not None:
        return jsonify(_plan_response(existing)), 200

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
        _persist_generated_plan(user_id, profile, plan, start_date, name)
    except Exception:
        app.logger.exception("Failed to persist generated plan for user_id=%s", user_id)
        return jsonify({"error": "Failed to save generated workout after retrying."}), 500

    return jsonify(_plan_response(plan_repo.get_unfinished_plan(user_id))), 200


@app.patch("/api/plans/<int:plan_id>/complete")
@require_admin
def complete_plan(plan_id):
    try:
        updated = plan_repo.mark_plan_completed(plan_id)
    except Exception:
        app.logger.exception("Failed to mark plan_id=%s completed", plan_id)
        return jsonify({"error": "Failed to mark the plan as completed."}), 500

    if updated is None:
        return jsonify({"error": f"Plan {plan_id} not found or already completed."}), 404
    return jsonify(updated), 200


@app.post("/api/users/<user_id>/progress-plan")
@require_admin
def progress_plan(user_id):
    existing = plan_repo.get_unfinished_plan(user_id)
    if existing is not None:
        return jsonify(_plan_response(existing)), 200

    last = plan_repo.get_last_completed_plan(user_id)
    if last is None:
        return jsonify({"error": f"No completed plan found for user_id={user_id}."}), 404

    try:
        plan_repo.create_progressed_plan(user_id, last["plan"], last["sessions"])
    except Exception:
        app.logger.exception("Failed to create progressed plan for user_id=%s", user_id)
        return jsonify({"error": "Failed to create the next plan."}), 500

    return jsonify(_plan_response(plan_repo.get_unfinished_plan(user_id))), 200


@app.get("/api/users/<user_id>/dashboard")
@require_auth
def get_dashboard(user_id):
    if user_id != g.user_id:
        return jsonify({"error": "You don't have access to this user's plan."}), 403

    existing = plan_repo.get_unfinished_plan(user_id)
    if existing is None:
        return jsonify({"error": "No plan found for this user."}), 404

    plan = existing["plan"]
    sessions = existing["sessions"]
    today = app_today()
    # Rest days have no session row; date them from the plan's start (day 1).
    plan_start = min(
        (date.fromisoformat(s["scheduled_date"]) - timedelta(days=day_number - 1)
         for day_number, s in sessions.items()),
        default=today,
    )

    found_next = False
    days = []
    for day in plan["schedule"]:
        session = sessions.get(day["day_number"], {})
        day_date = (
            date.fromisoformat(session["scheduled_date"]) if session
            else plan_start + timedelta(days=day["day_number"] - 1)
        )
        if day["is_rest_day"]:
            status = "rest"
        elif session.get("completed_at"):
            status = "completed"
        elif is_session_missed(session, today):
            status = "missed"
        elif not found_next:
            status = "next"
            found_next = True
        else:
            status = "upcoming"
        days.append({
            **day,
            "status": status,
            "date": day_date.isoformat(),
            "locked": not day["is_rest_day"] and day_date > today,
            "started_at": session.get("started_at"),
            "completed_at": session.get("completed_at"),
        })

    profile = plan_repo.get_profile(user_id) or {}
    session_duration_minutes = (profile.get("availability") or {}).get("session_duration_minutes")

    return jsonify({
        "plan_id": existing["id"],
        "plan_type": plan["plan_type"],
        "plan_selection_reason": plan["plan_selection_reason"],
        "medical_clearance_warning": plan["medical_clearance_warning"],
        "coach_notes": plan["coach_notes"],
        "safety_summary": plan["safety_summary"],
        "session_duration_minutes": session_duration_minutes,
        "days": days,
        "workouts": _dashboard_workouts(user_id, existing, today),
    }), 200


# Page size bounds for the dashboard's Past Workouts list.
PAST_WORKOUTS_DEFAULT_LIMIT = 2
PAST_WORKOUTS_MAX_LIMIT = 20

# Coach-facing fields of get_user_workout_history entries the client's own
# past-workouts list doesn't show.
_COACH_ONLY_WORKOUT_FIELDS = ("analysis", "analysis_audio_url", "has_feedback")


@app.get("/api/users/<user_id>/past-workouts")
@require_auth
def get_past_workouts(user_id):
    """One page of the client's past workouts (completed or missed, across
    every plan, newest first) for the dashboard's Past Workouts section,
    which loads more on demand: ?offset=0&limit=2. Also returns the totals so
    the section can show its counts before it's opened.

    Reads the whole history on each page (get_user_workout_history) — a
    client has tens of sessions, so slicing here is cheaper than paging in
    SQL across the plans/sessions join."""
    if user_id != g.user_id:
        return jsonify({"error": "You don't have access to this user's plan."}), 403
    try:
        offset = int(request.args.get("offset", 0))
        limit = int(request.args.get("limit", PAST_WORKOUTS_DEFAULT_LIMIT))
    except ValueError:
        return jsonify({"error": "'offset' and 'limit' must be whole numbers."}), 400
    if offset < 0:
        return jsonify({"error": "'offset' can't be negative."}), 400
    limit = max(1, min(PAST_WORKOUTS_MAX_LIMIT, limit))

    try:
        past = plan_repo.get_user_workout_history(user_id)["past"]
    except Exception:
        app.logger.exception("Failed to load past workouts for user_id=%s", user_id)
        return jsonify({"error": "Failed to load past workouts."}), 500

    today = app_today().isoformat()
    page = [
        {
            **{k: v for k, v in workout.items() if k not in _COACH_ONLY_WORKOUT_FIELDS},
            "is_today": workout["date"] == today,
            "is_next": False,
            "can_start": False,
        }
        for workout in past[offset:offset + limit]
    ]
    return jsonify({
        "workouts": page,
        "total": len(past),
        "completed": sum(1 for w in past if w["status"] == "completed"),
        "missed": sum(1 for w in past if w["status"] == "missed"),
    }), 200


@app.post("/api/users/<user_id>/joint-pain")
@require_admin
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
@require_admin
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


@app.post("/api/sessions/<int:session_id>/start")
@require_auth
def start_session(session_id):
    if denied := _deny_unless_session_open(session_id):
        return denied

    # Only women are asked, and the answer is only honoured for them.
    body = request.get_json(silent=True) or {}
    is_period = body.get("is_period") is True and plan_repo.get_gender(g.user_id) == "female"

    try:
        session = plan_repo.start_session(session_id, is_period)
    except Exception:
        app.logger.exception("Failed to start session_id=%s", session_id)
        return jsonify({"error": "Failed to start this workout."}), 500
    return jsonify(session), 200


@app.post("/api/sessions/<int:session_id>/feedback-audio")
@require_auth
def upload_feedback_audio(session_id):
    """Store the client's recorded voice feedback for a finished session
    (multipart field `audio`), replacing any earlier recording."""
    if denied := _deny_unless_session_open(session_id):
        return denied

    upload = request.files.get("audio")
    if upload is None:
        return jsonify({"error": "An 'audio' file is required."}), 400
    content_type = (upload.mimetype or "").split(";")[0].strip().lower()
    path = feedback_path(session_id, content_type)
    if path is None:
        return jsonify({"error": f"Unsupported audio type '{content_type}'."}), 415
    data = upload.read(MAX_FEEDBACK_BYTES + 1)
    if not data:
        return jsonify({"error": "The recording is empty."}), 400
    if len(data) > MAX_FEEDBACK_BYTES:
        return jsonify({"error": "The recording is too long."}), 413

    try:
        previous_path = (plan_repo.get_session(session_id) or {}).get("feedback_audio_path")
        feedback_storage().store(data, path, content_type)
        plan_repo.set_feedback_audio_path(session_id, path)
        if previous_path and previous_path != path:
            try:
                feedback_storage().remove(previous_path)
            except Exception:
                app.logger.warning("Could not remove old feedback %s", previous_path, exc_info=True)
    except Exception:
        app.logger.exception("Failed to store voice feedback for session_id=%s", session_id)
        return jsonify({"error": "Failed to save your recording."}), 500
    return jsonify({"feedback_audio_path": path}), 200


@app.get("/api/sessions/<int:session_id>/feedback-audio")
@require_auth
def get_feedback_audio(session_id):
    """A temporary link to the session's voice feedback, 404 if none."""
    if denied := _deny_unless_session_open(session_id):
        return denied
    path = (plan_repo.get_session(session_id) or {}).get("feedback_audio_path")
    if not path:
        return jsonify({"error": "No voice feedback for this session."}), 404
    return jsonify({"url": feedback_storage().create_signed_url(path, SIGNED_URL_TTL_SECONDS)}), 200


@app.get("/api/admin/sessions/<int:session_id>/feedback-audio")
@require_admin
def get_feedback_audio_for_coach(session_id):
    """The coach's temporary link to a session's voice feedback."""
    path = (plan_repo.get_session(session_id) or {}).get("feedback_audio_path")
    if not path:
        return jsonify({"error": "No voice feedback for this session."}), 404
    return jsonify({"url": feedback_storage().create_signed_url(path, SIGNED_URL_TTL_SECONDS)}), 200


@app.patch("/api/sessions/<int:session_id>/exercises/<int:session_exercise_id>/sets/<int:set_number>")
@require_auth
def log_set(session_id, session_exercise_id, set_number):
    if denied := _deny_unless_session_open(session_id):
        return denied

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
@require_auth
def log_rpe(session_id, session_exercise_id):
    if denied := _deny_unless_session_open(session_id):
        return denied

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


@app.post("/api/sessions/<int:session_id>/complete")
@require_auth
def complete_session(session_id):
    if denied := _deny_unless_session_open(session_id):
        return denied

    try:
        summary = plan_repo.complete_session(session_id)
    except Exception:
        app.logger.exception("Failed to complete session_id=%s", session_id)
        return jsonify({"error": "Failed to complete this workout."}), 500

    if summary is None:
        return jsonify({"error": f"Session {session_id} not found."}), 404

    return jsonify(summary), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001, debug=True)
