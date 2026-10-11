"""Session cookies, WebAuthn relying-party config, and route guards.

Sign-in is passkey-only (see backend/controllers/auth_controller.py). A
successful sign-in sets an opaque random token in the `fc_session` cookie;
only its SHA-256 hash is stored in `auth_sessions`.
"""
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import List, Optional

from flask import g, jsonify, request

from backend.repository.auth_repository import AuthRepository

SESSION_COOKIE = "fc_session"
SESSION_TTL = timedelta(days=30)
CHALLENGE_TTL = timedelta(minutes=5)
ENROLLMENT_TTL = timedelta(hours=48)

auth_repo = AuthRepository()


def rp_id() -> str:
    return os.environ.get("WEBAUTHN_RP_ID", "localhost")


def rp_name() -> str:
    return os.environ.get("WEBAUTHN_RP_NAME", "AI Fitness Coach")


def allowed_origins() -> List[str]:
    raw = os.environ.get("WEBAUTHN_ORIGINS", "http://localhost:5173")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(response, user_id: str) -> None:
    token = secrets.token_urlsafe(32)
    auth_repo.create_session(user_id, hash_token(token), utcnow() + SESSION_TTL)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        samesite="Lax",
        # Browsers only allow non-Secure cookies over plain http on localhost.
        secure=rp_id() != "localhost",
        path="/api",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/api")


def current_user_id() -> Optional[str]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    session = auth_repo.get_active_session(hash_token(token))
    return session["user_id"] if session else None


def require_auth(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        user_id = current_user_id()
        if user_id is None:
            return jsonify({"error": "Not signed in."}), 401
        g.user_id = user_id
        return view(*args, **kwargs)
    return wrapper


def require_admin(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        expected = os.environ.get("ADMIN_API_KEY")
        provided = request.headers.get("X-Admin-Key", "")
        if not expected or not hmac.compare_digest(provided, expected):
            return jsonify({"error": "Admin key required."}), 401
        return view(*args, **kwargs)
    return wrapper
