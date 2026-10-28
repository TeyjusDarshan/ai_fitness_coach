import os
import secrets
from datetime import datetime, timezone
from typing import List, Optional

from dotenv import load_dotenv
from supabase import create_client, Client
from webauthn.helpers import bytes_to_base64url

load_dotenv()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuthRepository:
    """Persists passkey credentials, WebAuthn challenges, login sessions and
    coach-issued enrollment tokens.

    Tokens (session cookies, enrollment links) are only ever stored as
    SHA-256 hashes — callers hash before passing them in.
    """

    def __init__(self, client: Optional[Client] = None):
        if client is not None:
            self.client = client
        else:
            url = os.environ.get("SUPABASE_URL")
            key = os.environ.get("SUPABASE_KEY")
            self.client = create_client(url, key)

    def get_user_auth_row(self, user_id: str) -> Optional[dict]:
        rows = (
            self.client.table("user_profiles")
            .select("user_id, name, gender, webauthn_user_handle")
            .eq("user_id", user_id)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def get_or_create_user_handle(self, user_id: str) -> str:
        """The user's stable, random WebAuthn user.id (base64url).

        Written only where it's still NULL and then re-read, so two racing
        first enrollments settle on the same handle.
        """
        row = self.get_user_auth_row(user_id)
        if row and row.get("webauthn_user_handle"):
            return row["webauthn_user_handle"]
        (
            self.client.table("user_profiles")
            .update({"webauthn_user_handle": bytes_to_base64url(secrets.token_bytes(32))})
            .eq("user_id", user_id)
            .is_("webauthn_user_handle", "null")
            .execute()
        )
        return self.get_user_auth_row(user_id)["webauthn_user_handle"]

    def create_challenge(
        self, challenge: str, purpose: str, user_id: Optional[str], expires_at: datetime
    ) -> None:
        self.client.table("auth_challenges").insert({
            "challenge": challenge,
            "purpose": purpose,
            "user_id": user_id,
            "expires_at": expires_at.isoformat(),
        }).execute()

    def consume_challenge(self, challenge: str, purpose: str) -> Optional[dict]:
        """Delete and return the matching unexpired challenge — a single
        DELETE, so a challenge can be redeemed at most once."""
        rows = (
            self.client.table("auth_challenges")
            .delete()
            .eq("challenge", challenge)
            .eq("purpose", purpose)
            .gt("expires_at", _now_iso())
            .execute()
            .data
        )
        return rows[0] if rows else None

    def delete_expired_challenges(self) -> None:
        self.client.table("auth_challenges").delete().lt("expires_at", _now_iso()).execute()

    def create_session(self, user_id: str, token_hash: str, expires_at: datetime) -> None:
        self.client.table("auth_sessions").insert({
            "user_id": user_id,
            "token_hash": token_hash,
            "expires_at": expires_at.isoformat(),
            "last_seen_at": _now_iso(),
        }).execute()

    def get_active_session(self, token_hash: str) -> Optional[dict]:
        rows = (
            self.client.table("auth_sessions")
            .select("user_id, expires_at")
            .eq("token_hash", token_hash)
            .gt("expires_at", _now_iso())
            .execute()
            .data
        )
        return rows[0] if rows else None

    def touch_session(self, token_hash: str) -> None:
        (
            self.client.table("auth_sessions")
            .update({"last_seen_at": _now_iso()})
            .eq("token_hash", token_hash)
            .execute()
        )

    def delete_session(self, token_hash: str) -> None:
        self.client.table("auth_sessions").delete().eq("token_hash", token_hash).execute()

    def list_credential_ids(self, user_id: str) -> List[str]:
        rows = (
            self.client.table("user_passkeys")
            .select("credential_id")
            .eq("user_id", user_id)
            .execute()
            .data
        )
        return [row["credential_id"] for row in rows]

    def get_passkey(self, credential_id: str) -> Optional[dict]:
        rows = (
            self.client.table("user_passkeys")
            .select("*")
            .eq("credential_id", credential_id)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def add_passkey(self, passkey: dict) -> None:
        self.client.table("user_passkeys").insert(passkey).execute()

    def update_passkey_usage(self, credential_id: str, sign_count: int) -> None:
        (
            self.client.table("user_passkeys")
            .update({"sign_count": sign_count, "last_used_at": _now_iso()})
            .eq("credential_id", credential_id)
            .execute()
        )

    def create_enrollment_token(self, user_id: str, token_hash: str, expires_at: datetime) -> None:
        """Replace any still-unused link for this user, so only the newest works."""
        (
            self.client.table("passkey_enrollment_tokens")
            .delete()
            .eq("user_id", user_id)
            .is_("used_at", "null")
            .execute()
        )
        self.client.table("passkey_enrollment_tokens").insert({
            "user_id": user_id,
            "token_hash": token_hash,
            "expires_at": expires_at.isoformat(),
        }).execute()

    def get_valid_enrollment_token(self, token_hash: str) -> Optional[dict]:
        rows = (
            self.client.table("passkey_enrollment_tokens")
            .select("user_id")
            .eq("token_hash", token_hash)
            .is_("used_at", "null")
            .gt("expires_at", _now_iso())
            .execute()
            .data
        )
        return rows[0] if rows else None

    def consume_enrollment_token(self, token_hash: str) -> bool:
        """Mark the token used — a single conditional UPDATE, so it can only
        succeed once even under concurrent requests."""
        rows = (
            self.client.table("passkey_enrollment_tokens")
            .update({"used_at": _now_iso()})
            .eq("token_hash", token_hash)
            .is_("used_at", "null")
            .gt("expires_at", _now_iso())
            .execute()
            .data
        )
        return bool(rows)
