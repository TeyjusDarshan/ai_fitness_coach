"""Coach-only endpoints behind the /admin plan builder (X-Admin-Key).

Flow: POST /api/admin/users/profile turns the coach's free-form notes about
a client into a structured profile (preprocessor agent) and upserts it;
GET /api/admin/plan-builder serves the DAY_TEMPLATES skeletons and the
exercise library; POST /api/admin/users/<user_id>/initial-plan saves the
plan the coach filled in by hand as the user's first plan, with one session
per training day scheduled from the coach's start date.
"""
import logging
import re
from datetime import date

from flask import Blueprint, jsonify, request

from agents.preprocessor_agent import generate_user_profile
from agents.prompts_v1 import DAY_TEMPLATES
from backend.auth import auth_repo, require_admin
from backend.controllers.auth_controller import mint_enrollment_link
from backend.repository.workout_plan_repository import WorkoutPlanRepository, app_today
from backend.repository.workout_repository import WorkoutRepository

logger = logging.getLogger(__name__)

GENDERS = ("male", "female", "other")

admin_plan_bp = Blueprint("admin_plan", __name__)
plan_repo = WorkoutPlanRepository()
exercise_repo = WorkoutRepository()

USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
MAX_NAME_LENGTH = 100
MAX_SETS = 10
MAX_REPS = 100
MANUAL_PLAN_REASON = "Built manually by coach"
NO_CLEARANCE_WARNING = (
    "Client has not reported medical clearance for exercise — confirm with their doctor before starting."
)


class PlanValidationError(ValueError):
    pass


def _is_int_in(value, low, high):
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _unfinished_plan_conflict(user_id):
    """409 response if user_id already has an unfinished plan, else None."""
    existing = plan_repo.get_unfinished_plan(user_id)
    if existing is None:
        return None
    return jsonify({
        "error": f"User {user_id} already has an unfinished plan (plan {existing['id']}).",
        "plan_id": existing["id"],
    }), 409


def _parse_start_date(value):
    """The plan's start date (day 1's scheduled_date): an ISO YYYY-MM-DD
    string, not before today."""
    try:
        start_date = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise PlanValidationError("'start_date' (YYYY-MM-DD) is required.")
    if start_date < app_today():
        raise PlanValidationError("'start_date' can't be in the past.")
    return start_date


@admin_plan_bp.post("/api/admin/users/profile")
@require_admin
def create_profile():
    body = request.get_json(silent=True) or {}
    user_id = body.get("user_id")
    name = body.get("name")
    raw_user_text = body.get("raw_user_text")

    if not isinstance(user_id, str) or not USER_ID_PATTERN.match(user_id):
        return jsonify({"error": "'user_id' must be 1-64 letters, digits, '_', '-' or '.'."}), 400
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > MAX_NAME_LENGTH:
        return jsonify({"error": f"'name' is required (max {MAX_NAME_LENGTH} characters)."}), 400
    name = name.strip()
    gender = body.get("gender")
    if gender is not None and gender not in GENDERS:
        return jsonify({"error": f"'gender' must be one of {', '.join(GENDERS)}."}), 400
    if not isinstance(raw_user_text, str) or not raw_user_text.strip():
        return jsonify({"error": "'raw_user_text' is required."}), 400

    # Checked before the (slow, billed) LLM call so a client mid-plan never
    # has their profile overwritten out from under that plan.
    if conflict := _unfinished_plan_conflict(user_id):
        return conflict

    user_created = not plan_repo.user_exists(user_id)

    try:
        profile = generate_user_profile(raw_user_text)
    except ValueError as e:
        return jsonify({"error": f"Failed to extract client profile: {e}"}), 502

    # The preprocessor assigns its own placeholder user_id — the coach's id
    # is authoritative.
    profile["user_id"] = user_id

    try:
        plan_repo.upsert_user_profile(user_id, profile, name, gender)
    except Exception:
        logger.exception("Failed to upsert profile for user_id=%s", user_id)
        return jsonify({"error": "Failed to save the client profile."}), 500

    return jsonify({
        "user_id": user_id, "name": name, "gender": gender, "profile": profile, "user_created": user_created,
    }), 200


@admin_plan_bp.get("/api/admin/plan-builder")
@require_admin
def plan_builder_options():
    try:
        exercises = exercise_repo.list_exercises()
    except Exception:
        logger.exception("Failed to load the exercise library")
        return jsonify({"error": "Failed to load the exercise library."}), 500
    return jsonify({"templates": DAY_TEMPLATES, "exercises": exercises}), 200


def _build_plan(body, exercises_by_id, profile):
    """Validate the coach's slot picks against DAY_TEMPLATES and return a
    plan dict in the shape WorkoutPlanRepository.create_plan consumes."""
    plan_type = body.get("plan_type")
    if plan_type not in DAY_TEMPLATES:
        raise PlanValidationError(f"'plan_type' must be one of {sorted(DAY_TEMPLATES)}.")

    coach_notes = body.get("coach_notes")
    if coach_notes is not None and not isinstance(coach_notes, str):
        raise PlanValidationError("'coach_notes' must be a string.")

    days = body.get("days")
    if not isinstance(days, list):
        raise PlanValidationError("'days' (list) is required.")

    template = DAY_TEMPLATES[plan_type]["schedule"]
    training_days = {day["day_number"] for day in template if not day["is_rest_day"]}
    submitted = {}
    for day in days:
        day_number = day.get("day_number") if isinstance(day, dict) else None
        if day_number not in training_days:
            raise PlanValidationError(
                f"Every entry in 'days' needs a 'day_number' that is a training day of {plan_type}: "
                f"{sorted(training_days)}."
            )
        if day_number in submitted:
            raise PlanValidationError(f"Day {day_number} appears more than once.")
        submitted[day_number] = day
    missing = training_days - submitted.keys()
    if missing:
        raise PlanValidationError(f"Missing training days: {sorted(missing)}.")

    schedule = []
    for template_day in template:
        day_number = template_day["day_number"]
        day = {
            "day_number": day_number,
            "day_label": template_day["day_label"],
            "split_name": template_day["split_name"],
            "is_rest_day": template_day["is_rest_day"],
            "primary": [],
            "secondary": [],
        }
        if not template_day["is_rest_day"]:
            for category in ("primary", "secondary"):
                slots = template_day[category]
                entries = submitted[day_number].get(category)
                if not isinstance(entries, list) or len(entries) != len(slots):
                    raise PlanValidationError(
                        f"Day {day_number} needs exactly {len(slots)} {category} exercise(s)."
                    )
                day[category] = [
                    _build_entry(entry, slot, exercises_by_id, f"Day {day_number} {slot['slot']}")
                    for entry, slot in zip(entries, slots)
                ]
        schedule.append(day)

    health = (profile or {}).get("health") or {}
    return {
        "plan_type": plan_type,
        "plan_selection_reason": MANUAL_PLAN_REASON,
        "medical_clearance_warning": (
            NO_CLEARANCE_WARNING if health.get("medical_clearance_obtained") is False else None
        ),
        "coach_notes": (coach_notes or "").strip() or None,
        "safety_summary": None,
        "schedule": schedule,
    }


def _build_entry(entry, slot, exercises_by_id, where):
    if not isinstance(entry, dict):
        raise PlanValidationError(f"{where}: each slot must be an object.")
    exercise_id = entry.get("exercise_id")
    # isinstance check first: True == 1 would otherwise match exercise 1.
    exercise = exercises_by_id.get(exercise_id) if isinstance(exercise_id, int) and not isinstance(
        exercise_id, bool
    ) else None
    if exercise is None:
        raise PlanValidationError(f"{where}: unknown 'exercise_id'.")
    if not _is_int_in(entry.get("sets"), 1, MAX_SETS):
        raise PlanValidationError(f"{where}: 'sets' must be an int from 1 to {MAX_SETS}.")
    if not _is_int_in(entry.get("reps"), 1, MAX_REPS):
        raise PlanValidationError(f"{where}: 'reps' must be an int from 1 to {MAX_REPS}.")
    note = entry.get("note")
    if note is not None and not isinstance(note, str):
        raise PlanValidationError(f"{where}: 'note' must be a string.")

    min_reps, max_reps = exercise.get("min_reps"), exercise.get("max_reps")
    return {
        "exercise_id": exercise["id"],
        "slot": slot["slot"],
        "sets": entry["sets"],
        "reps": str(entry["reps"]),
        "rep_range": f"{min_reps}-{max_reps}" if min_reps is not None and max_reps is not None else None,
        "note": (note or "").strip() or None,
    }


@admin_plan_bp.post("/api/admin/users/<user_id>/initial-plan")
@require_admin
def create_initial_plan(user_id):
    profile = plan_repo.get_profile(user_id)
    if profile is None:
        return jsonify({"error": f"User {user_id} not found — generate their profile first."}), 404
    if conflict := _unfinished_plan_conflict(user_id):
        return conflict

    body = request.get_json(silent=True) or {}
    try:
        exercises_by_id = {ex["id"]: ex for ex in exercise_repo.list_exercises()}
    except Exception:
        logger.exception("Failed to load the exercise library")
        return jsonify({"error": "Failed to load the exercise library."}), 500

    try:
        start_date = _parse_start_date(body.get("start_date"))
        plan = _build_plan(body, exercises_by_id, profile)
    except PlanValidationError as e:
        return jsonify({"error": str(e)}), 400

    try:
        created = plan_repo.create_plan(user_id, plan, start_date)
    except Exception:
        logger.exception("Failed to save initial plan for user_id=%s", user_id)
        return jsonify({"error": "Failed to save the plan."}), 500

    # Best-effort: the plan is saved either way, and the coach can mint a
    # link later via POST /api/admin/users/<user_id>/enrollment-link.
    enrollment = None
    try:
        if not auth_repo.list_credential_ids(user_id):
            enrollment = mint_enrollment_link(user_id)
    except Exception:
        logger.exception("Failed to mint enrollment link for user_id=%s", user_id)

    return jsonify({"user_id": user_id, "plan_id": created["id"], "enrollment": enrollment}), 201
