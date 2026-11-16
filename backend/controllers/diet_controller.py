"""Voice diet tracking endpoints.

The client records what she ate on the PWA's Food screen; the recording is
stored and a meal-log event published, and the meal-log consumer
(diet/consumer.py) turns it into items — dishes with their ingredients —
which she then reviews: change a portion, open a dish and change its
ingredients (which becomes her own version of that dish), or remove it.
She sees protein and fibre against her targets; the coach sees every
nutrient per day in Monitor clients, and reviews what Claude estimated
(dishes, recipes, ingredients) in the Foods tab.
"""
import logging
from datetime import date, datetime, timedelta, timezone

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
from diet.nutrition import DEFAULT_TARGETS, MACROS, MICROS, PORTION_UNITS, rounded, targets_for
from diet.repository import DietRepository
from diet.validate import DISPLAY_UNITS, MAX_PORTION_GRAMS, MAX_INGREDIENT_PER_100G, MIN_PORTION_GRAMS

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


# --- the client's endpoints ------------------------------------------------

@diet_bp.post("/api/meal-logs")
@require_auth
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
    log = diet_repo.get_meal_log_detail(meal_log_id)
    return log if log and log["user_id"] == g.user_id else None


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
@require_auth
def get_meal_log(meal_log_id):
    log = _own_log(meal_log_id)
    if log is None:
        return jsonify(_NO_LOG[0]), _NO_LOG[1]
    return jsonify(service.shape_log(log)), 200


@diet_bp.post("/api/meal-logs/<int:meal_log_id>/confirm")
@require_auth
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
@require_auth
def delete_meal_log(meal_log_id):
    """Discard a log (she's recording it again) and its recording."""
    log = _own_log(meal_log_id)
    if log is None:
        return jsonify(_NO_LOG[0]), _NO_LOG[1]
    diet_repo.delete_meal_log(meal_log_id)
    if log.get("audio_path"):
        try:
            feedback_storage().remove(log["audio_path"])
        except Exception:
            logger.warning("Could not remove meal recording %s", log["audio_path"], exc_info=True)
    return jsonify({"deleted": True}), 200


@diet_bp.get("/api/meal-log-items/<int:item_id>")
@require_auth
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
@require_auth
def edit_meal_log_item(item_id):
    """`{"quantity": n}` — a bigger or smaller portion of the same dish."""
    quantity = _number((request.get_json(silent=True) or {}).get("quantity"))
    if quantity is None:
        return jsonify({"error": "'quantity' must be a number."}), 400
    return _edit_item(item_id, lambda item: service.change_quantity(diet_repo, item, quantity))


@diet_bp.delete("/api/meal-log-items/<int:item_id>")
@require_auth
def delete_meal_log_item(item_id):
    item = _own_item(item_id)
    if item is None:
        return jsonify(_NO_ITEM[0]), _NO_ITEM[1]
    diet_repo.delete_item(item_id)
    return jsonify({"deleted": True}), 200


@diet_bp.patch("/api/meal-log-items/<int:item_id>/ingredients/<int:ingredient_id>")
@require_auth
def edit_meal_log_item_ingredient(item_id, ingredient_id):
    """`{"grams": n}` — how much of one ingredient is in this dish (0
    removes it). Also saved as her own version of the dish."""
    grams = _number((request.get_json(silent=True) or {}).get("grams"))
    if grams is None:
        return jsonify({"error": "'grams' must be a number."}), 400
    return _edit_item(
        item_id, lambda item: service.change_ingredient(diet_repo, item, g.user_id, ingredient_id, grams)
    )


@diet_bp.post("/api/meal-log-items/<int:item_id>/reset-recipe")
@require_auth
def reset_meal_log_item_recipe(item_id):
    """Drop her version of the dish and restore this entry's ingredients."""
    return _edit_item(item_id, lambda item: service.reset_recipe(diet_repo, item, g.user_id))


@diet_bp.get("/api/users/<user_id>/diet")
@require_auth
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
    ingredients and what was assumed, edited or still unverified)."""
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


@diet_bp.get("/api/admin/foods")
@require_admin
def list_foods():
    """The food library: every dish (unit weights, recipe) and every
    ingredient (nutrients per 100 g), unverified first."""
    return jsonify({
        "foods": diet_repo.list_foods(),
        "ingredients": diet_repo.list_ingredients(),
        "portion_units": list(PORTION_UNITS),
        "nutrients": list(MACROS + MICROS),
    }), 200


def _aliases(value):
    if not isinstance(value, list) or not all(isinstance(alias, str) for alias in value):
        return None
    return [alias.strip()[:80] for alias in value if alias.strip()][:20]


@diet_bp.patch("/api/admin/foods/<int:food_id>")
@require_admin
def edit_food(food_id):
    """The coach's correction of a dish. Any of: `aliases` (list),
    `default_unit`, `verified`, `portions` ({unit: grams}, the whole set),
    `recipe` ([{ingredient_id, grams_per_100g}], the whole recipe). A
    changed recipe applies to logs from now on; clients' own versions of
    the dish are left as they are."""
    body = request.get_json(silent=True) or {}
    fields = {"source": "coach", "updated_at": datetime.now(timezone.utc).isoformat()}
    if "aliases" in body:
        if (aliases := _aliases(body["aliases"])) is None:
            return jsonify({"error": "'aliases' must be a list of text."}), 400
        fields["aliases"] = aliases
    if "verified" in body:
        if not isinstance(body["verified"], bool):
            return jsonify({"error": "'verified' must be true or false."}), 400
        fields["verified"] = body["verified"]

    portions = None
    if "portions" in body:
        raw = body["portions"]
        if not isinstance(raw, dict) or not raw:
            return jsonify({"error": "'portions' must list at least one unit."}), 400
        portions = {}
        for unit, grams in raw.items():
            grams = _number(grams)
            if unit not in PORTION_UNITS or grams is None or not MIN_PORTION_GRAMS <= grams <= MAX_PORTION_GRAMS:
                return jsonify({
                    "error": f"Each unit weight must be {MIN_PORTION_GRAMS}–{MAX_PORTION_GRAMS} g of a known unit."
                }), 400
            portions[unit] = round(grams, 1)

    existing = diet_repo.get_foods([food_id]).get(food_id)
    if existing is None:
        return jsonify({"error": "No such dish."}), 404
    if "default_unit" in body:
        if body["default_unit"] not in (portions if portions is not None else existing["portions"]):
            return jsonify({"error": "'default_unit' must be one of the dish's units."}), 400
        fields["default_unit"] = body["default_unit"]
    elif portions is not None and existing["default_unit"] not in portions:
        return jsonify({"error": "The dish's default unit must keep a weight."}), 400

    recipe = None
    if "recipe" in body:
        raw = body["recipe"]
        known = set(diet_repo.ingredient_ids())
        if not isinstance(raw, list) or not raw:
            return jsonify({"error": "'recipe' must list at least one ingredient."}), 400
        merged = {}
        for line in raw:
            grams = _number(line.get("grams_per_100g")) if isinstance(line, dict) else None
            if grams is None or not 0 < grams <= MAX_INGREDIENT_PER_100G or line.get("ingredient_id") not in known:
                return jsonify({
                    "error": f"Each recipe line needs a known ingredient and 0–{MAX_INGREDIENT_PER_100G} g per 100 g."
                }), 400
            merged[line["ingredient_id"]] = round(grams, 2)
        recipe = [{"ingredient_id": key, "grams_per_100g": value} for key, value in merged.items()]

    try:
        diet_repo.update_food(food_id, fields, portions, recipe)
    except Exception:
        logger.exception("Failed to edit food_id=%s", food_id)
        return jsonify({"error": "Failed to save the dish."}), 500
    return jsonify(diet_repo.get_foods([food_id])[food_id]), 200


@diet_bp.patch("/api/admin/ingredients/<int:ingredient_id>")
@require_admin
def edit_ingredient(ingredient_id):
    """The coach's correction of an ingredient: any nutrient (per 100 g
    raw; a micronutrient may be null for unknown), `aliases`, `verified`,
    `display_unit` + `grams_per_display_unit`. Nutrients are read from here
    whenever a day is totalled, so a correction changes past days too."""
    body = request.get_json(silent=True) or {}
    fields = {"source": "coach", "updated_at": datetime.now(timezone.utc).isoformat()}
    for key in MACROS + MICROS:
        if key not in body:
            continue
        value = _number(body[key])
        if body[key] is None and key in MICROS:
            fields[key] = None
        elif value is None or not 0 <= value <= (900 if key == "energy_kcal" else 100000):
            return jsonify({"error": f"'{key}' must be a number, 0 or more."}), 400
        else:
            fields[key] = value
    if "aliases" in body:
        if (aliases := _aliases(body["aliases"])) is None:
            return jsonify({"error": "'aliases' must be a list of text."}), 400
        fields["aliases"] = aliases
    if "verified" in body:
        if not isinstance(body["verified"], bool):
            return jsonify({"error": "'verified' must be true or false."}), 400
        fields["verified"] = body["verified"]
    if "display_unit" in body:
        unit, per_unit = body["display_unit"], _number(body.get("grams_per_display_unit"))
        if unit is None:
            fields["display_unit"], fields["grams_per_display_unit"] = None, None
        elif unit not in DISPLAY_UNITS or per_unit is None or not 0 < per_unit <= 500:
            return jsonify({"error": "'display_unit' needs a known unit and its weight in grams."}), 400
        else:
            fields["display_unit"], fields["grams_per_display_unit"] = unit, per_unit

    try:
        if not diet_repo.update_ingredient(ingredient_id, fields):
            return jsonify({"error": "No such ingredient."}), 404
    except Exception:
        logger.exception("Failed to edit ingredient_id=%s", ingredient_id)
        return jsonify({"error": "Failed to save the ingredient."}), 500
    return jsonify({"id": ingredient_id, **fields}), 200
