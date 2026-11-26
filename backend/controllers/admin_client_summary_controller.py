"""The client summary for the PWA's /admin "Monitor clients" tab.

`GET  /api/admin/users/<user_id>/summary` — the latest version (or null).
`POST /api/admin/users/<user_id>/summary` — update it from the previous
version plus what arrived since (`{"rebuild": true}` starts again from her
whole history). Runs Sonnet inside the request (~10–25 s). See
backend/client_summary.
"""
import logging
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request

from backend.auth import require_admin
from backend.client_summary.repository import ClientSummaryRepository
from backend.client_summary.service import ClientNotFoundError, latest_summary, summarize_client
from backend.controllers.admin_monitor_controller import plan_repo

logger = logging.getLogger(__name__)

admin_client_summary_bp = Blueprint("admin_client_summary", __name__)

summary_repo = ClientSummaryRepository(plan_repo.client)


def _summarize(message: str, user_id: Optional[str]) -> tuple:
    # Imported on first use: the Anthropic SDK isn't needed at cold start.
    from backend.client_summary import agent
    return agent.summarize(message, user_id)


def _public(summary: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if summary is None:
        return None
    keys = ("version", "text", "created_at", "covers_from", "covers_until", "word_count", "model", "rebuilt")
    return {key: summary.get(key) for key in keys}


@admin_client_summary_bp.get("/api/admin/users/<user_id>/summary")
@require_admin
def get_summary(user_id):
    try:
        return jsonify({"summary": _public(latest_summary(summary_repo, user_id))})
    except Exception:
        logger.exception("Failed to load the client summary for %s", user_id)
        return jsonify({"error": "Failed to load the client summary."}), 500


@admin_client_summary_bp.post("/api/admin/users/<user_id>/summary")
@require_admin
def create_summary(user_id):
    body = request.get_json(silent=True) or {}
    rebuild = body.get("rebuild") is True
    try:
        result = summarize_client(summary_repo, plan_repo, user_id, _summarize, rebuild=rebuild)
    except ClientNotFoundError:
        return jsonify({"error": f"Client {user_id} not found."}), 404
    except Exception as exc:
        # A racing click for the same version loses on the unique key / the
        # existing file; anything else is the model or storage failing.
        text = str(exc).lower()
        if "duplicate" in text or "already exists" in text or "23505" in text:
            return jsonify({"error": "Another summary for this client was just saved. Reload to see it."}), 409
        logger.exception("Client summary failed for %s", user_id)
        return jsonify({"error": "The summary could not be made. Try again."}), 502
    return jsonify({"summary": _public(result["summary"]), "nothing_new": result["nothing_new"]})
