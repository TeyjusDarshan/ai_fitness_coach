"""AI spend per client for the PWA's /admin "Costs" tab: totals from the
ai_usage table (every Claude and Sarvam call, already priced in rupees) over
the last N days, per client and per feature. Read-only.
"""
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request

from ai_usage.prices import usd_inr_rate
from backend.auth import require_admin
from backend.controllers.admin_monitor_controller import plan_repo

logger = logging.getLogger(__name__)

admin_cost_bp = Blueprint("admin_cost", __name__)

DEFAULT_DAYS = 30
MAX_DAYS = 365
PAGE_SIZE = 1000  # Supabase returns at most 1000 rows per request.
DRY_RUN_PREFIX = "dry_run_"
UNATTRIBUTED = "(unattributed)"


def _fetch_usage(since: datetime, include_dry_runs: bool) -> List[Dict[str, Any]]:
    """Every ai_usage row since `since`, page by page."""
    rows, start = [], 0
    while True:
        query = (
            plan_repo.client.table("ai_usage")
            .select("user_id, session_id, provider, feature, calls, cost_inr_total, created_at")
            .gte("created_at", since.isoformat())
        )
        if not include_dry_runs:
            query = query.not_.like("feature", f"{DRY_RUN_PREFIX}%")
        page = query.order("id").range(start, start + PAGE_SIZE - 1).execute().data
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        start += PAGE_SIZE


def _money(value: float) -> float:
    return round(value, 2)


def _features(totals: Dict[tuple, Dict[str, float]]) -> List[Dict[str, Any]]:
    return sorted(
        (
            {"provider": provider, "feature": feature, "calls": int(t["calls"]), "inr": _money(t["inr"])}
            for (provider, feature), t in totals.items()
        ),
        key=lambda item: -item["inr"],
    )


def summarize_costs(
    rows: List[Dict[str, Any]], names: Dict[str, Optional[str]], days: int
) -> Dict[str, Any]:
    """ai_usage rows -> overall totals, per-feature totals and one entry per
    client (highest spend first) with their Claude/Sarvam split, workouts
    with spend, cost per workout and per-feature breakdown."""
    zero = lambda: {"inr": 0.0, "calls": 0}  # noqa: E731
    users: Dict[str, Dict[str, Any]] = {}
    overall_features: Dict[tuple, Dict[str, float]] = defaultdict(zero)
    overall = {"inr": 0.0, "anthropic": 0.0, "sarvam": 0.0, "calls": 0}

    for row in rows:
        inr = float(row.get("cost_inr_total") or 0)
        calls = int(row.get("calls") or 1)
        provider, feature = row["provider"], row["feature"]
        user_id = row.get("user_id") or UNATTRIBUTED

        overall["inr"] += inr
        overall[provider] = overall.get(provider, 0.0) + inr
        overall["calls"] += calls
        overall_features[(provider, feature)]["inr"] += inr
        overall_features[(provider, feature)]["calls"] += calls

        user = users.setdefault(user_id, {
            "inr": 0.0, "anthropic": 0.0, "sarvam": 0.0, "calls": 0, "sessions": set(),
            "session_inr": 0.0, "last_at": None, "features": defaultdict(zero),
        })
        user["inr"] += inr
        user[provider] = user.get(provider, 0.0) + inr
        user["calls"] += calls
        user["features"][(provider, feature)]["inr"] += inr
        user["features"][(provider, feature)]["calls"] += calls
        if row.get("session_id") is not None:
            user["sessions"].add(row["session_id"])
            user["session_inr"] += inr
        if user["last_at"] is None or row["created_at"] > user["last_at"]:
            user["last_at"] = row["created_at"]

    clients = []
    for user_id, user in users.items():
        workouts = len(user["sessions"])
        clients.append({
            "user_id": user_id,
            "name": names.get(user_id),
            "total_inr": _money(user["inr"]),
            "claude_inr": _money(user["anthropic"]),
            "sarvam_inr": _money(user["sarvam"]),
            "calls": user["calls"],
            "workouts": workouts,
            "per_workout_inr": _money(user["session_inr"] / workouts) if workouts else None,
            "last_at": user["last_at"],
            "by_feature": _features(user["features"]),
        })
    clients.sort(key=lambda client: -client["total_inr"])

    attributed = [c for c in clients if c["user_id"] != UNATTRIBUTED]
    return {
        "days": days,
        "usd_inr_rate": usd_inr_rate(),
        "total_inr": _money(overall["inr"]),
        "claude_inr": _money(overall.get("anthropic", 0.0)),
        "sarvam_inr": _money(overall.get("sarvam", 0.0)),
        "calls": overall["calls"],
        "active_clients": len(attributed),
        "per_client_inr": _money(sum(c["total_inr"] for c in attributed) / len(attributed)) if attributed else None,
        "by_feature": _features(overall_features),
        "clients": clients,
    }


@admin_cost_bp.get("/api/admin/costs")
@require_admin
def ai_costs():
    """`?days=30` (1-365) — AI spend per client over the last N days, in
    rupees (Claude converted at USD_INR_RATE). Dry runs are left out unless
    `?include_dry_runs=1`."""
    try:
        days = int(request.args.get("days", DEFAULT_DAYS))
    except ValueError:
        return jsonify({"error": "'days' must be a whole number."}), 400
    if not 1 <= days <= MAX_DAYS:
        return jsonify({"error": f"'days' must be from 1 to {MAX_DAYS}."}), 400
    include_dry_runs = request.args.get("include_dry_runs") in ("1", "true")

    since = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        rows = _fetch_usage(since, include_dry_runs)
        names = {row["user_id"]: row.get("name") for row in plan_repo.list_user_profiles()}
    except Exception:
        logger.exception("Failed to load AI costs")
        return jsonify({"error": "Failed to load AI costs."}), 500
    result = summarize_costs(rows, names, days)
    result["since"] = since.isoformat()
    result["include_dry_runs"] = include_dry_runs
    return jsonify(result), 200
