"""Voice diet tracking endpoints.

The client records what she ate on the PWA's Food screen; the recording is
stored and a meal-log event published, and the meal-log consumer
(voice_processor, via diet/pipeline.py) turns it into items — dishes with
the raw grams of each ingredient in her portion, written by Claude from the
names in ingredient_nutrition_reference, and their nutrients worked out from
that table — which she then reviews: change a portion, open a dish and
change an ingredient's amount on that entry, or remove it.
Off by default: every client endpoint is refused (require_diet) until the
coach switches diet tracking on for that client in Monitor clients.
She sees protein and fibre against her targets; the coach sees every
nutrient per day in Monitor clients.
"""
import logging
from datetime import date, datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, g, jsonify, request

from backend.auth import require_admin, require_auth
from backend.controllers.admin_monitor_controller import plan_repo
from backend.controllers.whatsapp_webhook_controller import kafka_producer
from backend.feedback_storage import (
    SIGNED_URL_TTL_SECONDS,
    UploadError,
    feedback_storage,
    meal_audio_path,
    read_audio_upload,
)
from backend.repository.workout_plan_repository import app_today
from diet import service
from diet.nutrition import DEFAULT_TARGETS, rounded, targets_for
from diet.repository import DietRepository

logger = logging.getLogger(__name__)

diet_bp = Blueprint("diet", __name__)

diet_repo = DietRepository(plan_repo.client)

# How far back she can open a day, and the coach's default / longest window.
MAX_DAYS_BACK = 60
DEFAULT_ADMIN_DAYS, MAX_ADMIN_DAYS = 7, 60
MAX_TARGET_GRAMS = 500


def _number(value):
    """A finite float from a JSON number, else None (bools don't count)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value == value and abs(value) != float("inf") else None


def require_diet(view):
    """A signed-in client's diet endpoint: refused (403) unless the coach
    has switched diet tracking on for her. Off by default."""
    @require_auth
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not diet_repo.is_enabled(g.user_id):
            return jsonify({"error": "Diet tracking isn't switched on for you.", "diet_disabled": True}), 403
        return view(*args, **kwargs)
    return wrapper


# --- the client's endpoints ------------------------------------------------

@diet_bp.post("/api/meal-logs")
@require_diet
def create_meal_log():
    """Start a meal log from a recording (multipart `audio`, optional
    `day`: `today` | `yesterday`). Answers straight away with the log in
    `processing`; the PWA then polls GET /api/meal-logs/<id>."""
    day = (request.form.get("day") or "today").strip().lower()
    if day not in ("today", "yesterday"):
        return jsonify({"error": "'day' must be 'today' or 'yesterday'."}), 400
    try:
        content_type, data = read_audio_upload(request.files.get("audio"))
    except UploadError as error:
        return jsonify({"error": error.message}), error.status

    logged_for = app_today() - timedelta(days=1 if day == "yesterday" else 0)
    try:
        log = diet_repo.create_meal_log(g.user_id, logged_for)
        path = meal_audio_path(log["id"], content_type)
        feedback_storage().store(data, path, content_type)
        diet_repo.update_meal_log(log["id"], {"audio_path": path})
    except Exception:
        logger.exception("Failed to store a meal recording for user_id=%s", g.user_id)
        return jsonify({"error": "Failed to save your recording."}), 500

    delivered = False
    try:
        delivered = kafka_producer.send_meal_log_event(log["id"])
    except Exception:
        logger.exception("Failed to publish meal_log_id=%s", log["id"])
    if not delivered:
        diet_repo.update_meal_log(log["id"], {"status": "failed", "error": "failed"})
        return jsonify({"error": "We couldn't start working on your recording. Please try again."}), 502
    return jsonify({"id": log["id"], "status": "processing", "logged_for": logged_for.isoformat()}), 201


def _own_log(meal_log_id):
    """Her log, unless she discarded it."""
    log = diet_repo.get_meal_log_detail(meal_log_id)
    return log if log and log["user_id"] == g.user_id and log["status"] != "discarded" else None


def _own_item(item_id):
    """Her item, if its log has been worked out (ready or confirmed)."""
    item = diet_repo.get_item(item_id)
    log = (item or {}).get("meal_logs") or {}
    if not item or log.get("user_id") != g.user_id or log.get("status") not in service.COUNTED_STATUSES:
        return None
    return item


_NO_LOG = ({"error": "No such meal log."}, 404)
_NO_ITEM = ({"error": "No such item."}, 404)


@diet_bp.get("/api/meal-logs/<int:meal_log_id>")
@require_diet
def get_meal_log(meal_log_id):
    log = _own_log(meal_log_id)
    if log is None:
        return jsonify(_NO_LOG[0]), _NO_LOG[1]
    return jsonify(service.shape_log(log)), 200


@diet_bp.post("/api/meal-logs/<int:meal_log_id>/confirm")
@require_diet
def confirm_meal_log(meal_log_id):
    """She looked at the items and tapped Done."""
    log = _own_log(meal_log_id)
    if log is None:
        return jsonify(_NO_LOG[0]), _NO_LOG[1]
    if log["status"] not in service.COUNTED_STATUSES:
        return jsonify({"error": "This log isn't ready yet."}), 409
    if log["status"] == "ready":
        diet_repo.update_meal_log(meal_log_id, {
            "status": "confirmed", "confirmed_at": datetime.now(timezone.utc).isoformat(),
        })
    return jsonify({"id": meal_log_id, "status": "confirmed"}), 200


@diet_bp.delete("/api/meal-logs/<int:meal_log_id>")
@require_diet
def delete_meal_log(meal_log_id):
    """Discard a log (she's recording it again, or removing one that
    failed) and delete its recording. The row is kept as `discarded`, hidden
    from her and the coach's food views, so its cost still counts in the
    Costs tab."""
    log = _own_log(meal_log_id)
    if log is None:
        return jsonify(_NO_LOG[0]), _NO_LOG[1]
    diet_repo.discard_meal_log(meal_log_id)
    if log.get("audio_path"):
        try:
            feedback_storage().remove(log["audio_path"])
        except Exception:
            logger.warning("Could not remove meal recording %s", log["audio_path"], exc_info=True)
    return jsonify({"deleted": True}), 200


@diet_bp.get("/api/meal-log-items/<int:item_id>")
@require_diet
def get_meal_log_item(item_id):
    """One logged dish with its ingredients and the amounts assumed."""
    item = _own_item(item_id)
    if item is None:
        return jsonify(_NO_ITEM[0]), _NO_ITEM[1]
    return jsonify({
        **service.shape_item(item, detail=True),
        "meal_log_id": item["meal_log_id"],
        "logged_for": item["meal_logs"]["logged_for"],
    }), 200


def _edit_item(item_id, apply):
    """Run one of her edits on her item and answer with the item as it is
    afterwards."""
    item = _own_item(item_id)
    if item is None:
        return jsonify(_NO_ITEM[0]), _NO_ITEM[1]
    try:
        apply(item)
    except service.EditError as error:
        return jsonify({"error": str(error)}), 400
    except Exception:
        logger.exception("Failed to edit meal_log_item_id=%s", item_id)
        return jsonify({"error": "Failed to save the change."}), 500
    return jsonify(service.shape_item(diet_repo.get_item(item_id), detail=True)), 200


@diet_bp.patch("/api/meal-log-items/<int:item_id>")
@require_diet
def edit_meal_log_item(item_id):
    """`{"quantity": n}` — a bigger or smaller portion of the same dish."""
    quantity = _number((request.get_json(silent=True) or {}).get("quantity"))
    if quantity is None:
        return jsonify({"error": "'quantity' must be a number."}), 400
    return _edit_item(item_id, lambda item: service.change_quantity(diet_repo, item, quantity))


@diet_bp.delete("/api/meal-log-items/<int:item_id>")
@require_diet
def delete_meal_log_item(item_id):
    item = _own_item(item_id)
    if item is None:
        return jsonify(_NO_ITEM[0]), _NO_ITEM[1]
    diet_repo.delete_item(item_id)
    return jsonify({"deleted": True}), 200


@diet_bp.patch("/api/meal-log-items/<int:item_id>/ingredients/<int:ingredient_id>")
@require_diet
def edit_meal_log_item_ingredient(item_id, ingredient_id):
    """`{"grams": n}` — how much of one ingredient is in this dish (0
    removes it). Only this entry changes."""
    grams = _number((request.get_json(silent=True) or {}).get("grams"))
    if grams is None:
        return jsonify({"error": "'grams' must be a number."}), 400
    return _edit_item(
        item_id, lambda item: service.change_ingredient(diet_repo, item, ingredient_id, grams)
    )


@diet_bp.post("/api/meal-log-items/<int:item_id>/reset")
@require_diet
def reset_meal_log_item(item_id):
    """Every ingredient of this entry back to the estimated amount."""
    return _edit_item(item_id, lambda item: service.reset_item(diet_repo, item))


@diet_bp.get("/api/users/<user_id>/diet")
@require_diet
def get_diet_day(user_id):
    """Her day (`?date=YYYY-MM-DD`, default today): protein and fibre
    against her targets, and what she logged."""
    if user_id != g.user_id:
        return jsonify({"error": "You don't have access to this user's food log."}), 403
    today = app_today()
    try:
        day = date.fromisoformat(request.args["date"]) if request.args.get("date") else today
    except ValueError:
        return jsonify({"error": "'date' must be YYYY-MM-DD."}), 400
    if not today - timedelta(days=MAX_DAYS_BACK) <= day <= today:
        return jsonify({"error": "That day is out of range."}), 400
    logs = diet_repo.list_meal_logs(user_id, day, day)
    return jsonify(service.day_summary(logs, diet_repo.get_targets(user_id), day.isoformat())), 200


# --- the coach's endpoints -------------------------------------------------

@diet_bp.get("/api/admin/users/<user_id>/diet")
@require_admin
def get_diet_for_coach(user_id):
    """The client's last `days` days (1–60, default 7), newest first: every
    nutrient per day, and each log with its transcript and items (with
    ingredients and what was assumed or edited)."""
    try:
        days = int(request.args.get("days", DEFAULT_ADMIN_DAYS))
    except ValueError:
        return jsonify({"error": "'days' must be a number."}), 400
    days = max(1, min(MAX_ADMIN_DAYS, days))
    if not plan_repo.user_exists(user_id):
        return jsonify({"error": f"No client with id {user_id}."}), 404

    today = app_today()
    logs = diet_repo.list_meal_logs(user_id, today - timedelta(days=days - 1), today)
    by_day = {}
    for log in logs:
        by_day.setdefault(log["logged_for"], []).append(log)
    return jsonify({
        "targets": targets_for(diet_repo.get_targets(user_id)),
        "days": [
            {
                "date": day,
                "totals": rounded(service.totals_of(day_logs)),
                "logs": [service.shape_log(log, detail=True, nutrients=True) for log in day_logs],
            }
            for day, day_logs in sorted(by_day.items(), reverse=True)
        ],
    }), 200


@diet_bp.patch("/api/admin/users/<user_id>/diet-tracking")
@require_admin
def set_diet_tracking(user_id):
    """`{"enabled": true | false}` — switch diet tracking on or off for a
    client. Off (the default) hides Food in her app and refuses every one
    of her diet endpoints; what she already logged is kept."""
    enabled = (request.get_json(silent=True) or {}).get("enabled")
    if not isinstance(enabled, bool):
        return jsonify({"error": "'enabled' must be true or false."}), 400
    if not diet_repo.set_enabled(user_id, enabled):
        return jsonify({"error": f"No client with id {user_id}."}), 404
    return jsonify({"user_id": user_id, "diet_enabled": enabled}), 200


@diet_bp.get("/api/admin/meal-logs/<int:meal_log_id>/audio")
@require_admin
def get_meal_audio_for_coach(meal_log_id):
    """A temporary link to a meal recording, 404 if there is none."""
    path = (diet_repo.get_meal_log(meal_log_id) or {}).get("audio_path")
    if not path:
        return jsonify({"error": "No recording for this log."}), 404
    return jsonify({"url": feedback_storage().create_signed_url(path, SIGNED_URL_TTL_SECONDS)}), 200


@diet_bp.patch("/api/admin/users/<user_id>/nutrition-targets")
@require_admin
def edit_nutrition_targets(user_id):
    """`{"protein_g": n, "fibre_g": n}` — her daily targets. A null or
    missing one goes back to the default."""
    body = request.get_json(silent=True) or {}
    targets = {}
    for key in DEFAULT_TARGETS:
        if body.get(key) is None:
            continue
        value = _number(body[key])
        if value is None or not 1 <= value <= MAX_TARGET_GRAMS:
            return jsonify({"error": f"'{key}' must be between 1 and {MAX_TARGET_GRAMS}."}), 400
        targets[key] = round(value)
    if not diet_repo.set_targets(user_id, targets or None):
        return jsonify({"error": f"No client with id {user_id}."}), 404
    return jsonify({"targets": targets_for(targets)}), 200
