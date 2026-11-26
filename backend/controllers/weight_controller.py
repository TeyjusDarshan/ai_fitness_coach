"""Weight tracking endpoints.

Readings come only from WhatsApp (the router's `weight_checkin`), so the
client only reads: her Food card and Weight Trend screen. The coach reads
the same view plus every closed week, and accepts or rejects the calorie
changes the weekly rules suggest (voice_processor/weight_jobs.py).
"""
import logging

from flask import Blueprint, g, jsonify, request

from backend.auth import require_admin
from backend.controllers.admin_monitor_controller import plan_repo
from backend.controllers.diet_controller import require_diet
from backend.controllers.whatsapp_webhook_controller import whatsapp_client
from diet.dates import today_in
from diet.nutrition import targets_for
from diet.weight import messages, service
from diet.weight.repository import WeightRepository

logger = logging.getLogger(__name__)

weight_bp = Blueprint("weight", __name__)

weight_repo = WeightRepository(plan_repo.client)

# Her range tabs: 4 / 8 / 12 weeks / all.
MAX_CHART_WEEKS = 104


def _chart_weeks():
    """(weeks or None for all, error response)."""
    value = request.args.get("weeks", str(service.DEFAULT_CHART_WEEKS))
    if value == "all":
        return None, None
    try:
        weeks = int(value)
    except ValueError:
        return None, (jsonify({"error": "'weeks' must be a number or 'all'."}), 400)
    return max(1, min(MAX_CHART_WEEKS, weeks)), None


def _view(profile, chart_weeks):
    today = today_in(profile.get("timezone"))
    start = service.chart_range_start(today, chart_weeks, weight_repo.first_reading(profile["user_id"]))
    readings = weight_repo.list_readings(profile["user_id"], start, today)
    weeks = weight_repo.list_weeks(profile["user_id"], limit=1)
    changes = weight_repo.list_changes(profile["user_id"])
    return service.view(profile, readings, weeks[0] if weeks else None, changes, today, chart_weeks), readings


@weight_bp.get("/api/users/<user_id>/weight")
@require_diet
def get_weight(user_id):
    """Her weight view (`?weeks=4|8|12|all`, default 8): today's reading,
    this week's average vs last week, her goal (target or maintain band),
    last Sunday's status, the weekly-average chart and calorie changes."""
    if user_id != g.user_id:
        return jsonify({"error": "You don't have access to this user's weight."}), 403
    chart_weeks, error = _chart_weeks()
    if error:
        return error
    profile = weight_repo.get_profile(user_id)
    if not profile or not profile.get("diet_setup"):
        return jsonify({"error": "Diet setup isn't done yet.", "setup_done": False}), 409
    result, _ = _view(profile, chart_weeks)
    return jsonify(result), 200


@weight_bp.get("/api/admin/users/<user_id>/weight")
@require_admin
def get_weight_for_coach(user_id):
    """Her view plus every reading in the range, every closed week (with
    the rule's numbers, outcome and the message), and every calorie change
    (pending ones can be accepted or rejected)."""
    chart_weeks, error = _chart_weeks()
    if error:
        return error
    profile = weight_repo.get_profile(user_id)
    if not profile:
        return jsonify({"error": f"No client with id {user_id}."}), 404
    if not profile.get("diet_setup"):
        return jsonify({"setup_done": False, "readings": [], "weeks": [], "changes": []}), 200
    result, readings = _view(profile, chart_weeks)
    return jsonify({
        **result,
        "setup_done": True,
        "readings": [{"date": r["measured_on"], "weight_kg": float(r["weight_kg"]), "source": r["source"],
                      "raw": r.get("raw")} for r in readings],
        "weeks": weight_repo.list_weeks(user_id),
        "changes": list(reversed(weight_repo.list_changes(user_id))),
    }), 200


def _notify(profile, change, outcome):
    """Tell her about an accepted change, only while her WhatsApp window is
    open (no templates). Best-effort."""
    phone = profile.get("whatsapp_number")
    if not weight_repo.reply_window_open(phone):
        return False
    text = messages.change_approved(
        profile.get("name"), (change.get("from_targets") or {}).get("energy_kcal"),
        change["to_targets"]["energy_kcal"], outcome, service.plan_of(profile)["goal"],
    )
    try:
        whatsapp_client.send_text(phone, text)
    except Exception:
        logger.exception("Failed to send the calorie-change message to user_id=%s", profile["user_id"])
        return False
    return True


@weight_bp.post("/api/admin/nutrition-target-changes/<int:change_id>/accept")
@require_admin
def accept_change(change_id):
    """Apply a pending suggestion: her targets become `to_targets` (and a
    goal switch makes her a maintain client at `new_goal_kg`). 409 if it
    isn't pending any more. She's told on WhatsApp if her window is open."""
    change = weight_repo.get_change(change_id)
    if not change:
        return jsonify({"error": "No such change."}), 404
    if not weight_repo.decide_change(change_id, "accepted"):
        return jsonify({"error": "This change isn't pending any more.", "status": change["status"]}), 409
    user_id = change["user_id"]
    weight_repo.set_targets(user_id, change["to_targets"])
    if change.get("new_goal"):
        weight_repo.set_weight_goal(user_id, change["new_goal"], change.get("new_goal_kg"))
    profile = weight_repo.get_profile(user_id) or {"user_id": user_id}
    outcome = None
    if change.get("week_id"):
        week = next((w for w in weight_repo.list_weeks(user_id) if w["id"] == change["week_id"]), None)
        outcome = (week or {}).get("outcome")
    notified = _notify(profile, change, outcome)
    if notified:
        weight_repo.update_change(change_id, {"notified_at": service.now_local(None).isoformat()})
    return jsonify({"id": change_id, "status": "accepted", "targets": targets_for(change["to_targets"]),
                    "notified": notified}), 200


@weight_bp.post("/api/admin/nutrition-target-changes/<int:change_id>/reject")
@require_admin
def reject_change(change_id):
    change = weight_repo.get_change(change_id)
    if not change:
        return jsonify({"error": "No such change."}), 404
    if not weight_repo.decide_change(change_id, "rejected"):
        return jsonify({"error": "This change isn't pending any more.", "status": change["status"]}), 409
    return jsonify({"id": change_id, "status": "rejected"}), 200
