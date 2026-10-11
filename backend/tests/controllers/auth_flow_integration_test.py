"""End-to-end passkey flow against the real Supabase project — no stubs.

A minimal software authenticator (a P-256 key pair) produces genuine
WebAuthn registration and assertion responses, so py_webauthn's real
signature/attestation checks and the real auth tables are exercised.

Creates a throwaway user_profiles row and deletes it afterwards; the
ON DELETE CASCADE FKs remove every auth row the test created.
"""
import hashlib
import json
import secrets
import sys
from unittest.mock import MagicMock, patch

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import bytes_to_base64url, encode_cbor

RP_ID = "localhost"
ORIGIN = "http://localhost:5173"
ADMIN_KEY = "integration-admin-key"

FLAG_UP, FLAG_UV, FLAG_AT = 0x01, 0x04, 0x40


class SoftwareAuthenticator:
    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = secrets.token_bytes(16)
        self.user_handle = None

    def _cose_public_key(self):
        numbers = self.key.public_key().public_numbers()
        return encode_cbor({
            1: 2, 3: -7, -1: 1,
            -2: numbers.x.to_bytes(32, "big"),
            -3: numbers.y.to_bytes(32, "big"),
        })

    @staticmethod
    def _client_data(kind, challenge):
        return json.dumps({"type": kind, "challenge": challenge, "origin": ORIGIN, "crossOrigin": False}).encode()

    def register(self, options):
        self.user_handle = options["user"]["id"]
        auth_data = (
            hashlib.sha256(RP_ID.encode()).digest()
            + bytes([FLAG_UP | FLAG_UV | FLAG_AT])
            + (0).to_bytes(4, "big")
            + bytes(16)
            + len(self.credential_id).to_bytes(2, "big")
            + self.credential_id
            + self._cose_public_key()
        )
        credential_id = bytes_to_base64url(self.credential_id)
        return {
            "id": credential_id,
            "rawId": credential_id,
            "type": "public-key",
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": bytes_to_base64url(self._client_data("webauthn.create", options["challenge"])),
                "attestationObject": bytes_to_base64url(
                    encode_cbor({"fmt": "none", "attStmt": {}, "authData": auth_data})
                ),
                "transports": ["internal"],
            },
        }

    def assert_(self, options):
        auth_data = hashlib.sha256(RP_ID.encode()).digest() + bytes([FLAG_UP | FLAG_UV]) + (0).to_bytes(4, "big")
        client_data = self._client_data("webauthn.get", options["challenge"])
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        credential_id = bytes_to_base64url(self.credential_id)
        return {
            "id": credential_id,
            "rawId": credential_id,
            "type": "public-key",
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "authenticatorData": bytes_to_base64url(auth_data),
                "signature": bytes_to_base64url(signature),
                "userHandle": self.user_handle,
            },
        }


@pytest.fixture
def live_app(monkeypatch):
    """backend.app with real Supabase repositories (Kafka/WhatsApp still mocked)."""
    monkeypatch.setenv("WEBAUTHN_RP_ID", RP_ID)
    monkeypatch.setenv("WEBAUTHN_ORIGINS", ORIGIN)
    monkeypatch.setenv("ADMIN_API_KEY", ADMIN_KEY)
    for name in ("backend.app", "backend.auth", "backend.controllers.auth_controller"):
        sys.modules.pop(name, None)
    with patch("backend.kafka_producer.client.Producer", return_value=MagicMock()), \
         patch("whatsapp_client.client.WhatsAppClient.__init__", return_value=None):
        import backend.app as module
        yield module
    for name in ("backend.app", "backend.auth", "backend.controllers.auth_controller"):
        sys.modules.pop(name, None)


@pytest.mark.integration
def test_enroll_sign_in_and_sign_out_with_a_real_passkey(live_app):
    user_id = f"zz_passkey_it_{secrets.token_hex(4)}"
    live_app.plan_repo.upsert_user_profile(user_id, {"integration_test": True})
    try:
        client = live_app.app.test_client()
        authenticator = SoftwareAuthenticator()

        link = client.post(f"/api/admin/users/{user_id}/enrollment-link", headers={"X-Admin-Key": ADMIN_KEY})
        assert link.status_code == 200
        token = link.get_json()["url"].split("token=", 1)[1]

        reg_options = client.post("/api/auth/register/options", json={"enrollment_token": token}).get_json()
        registered = client.post("/api/auth/register/verify", json={
            "enrollment_token": token, "credential": authenticator.register(reg_options),
        })
        assert registered.status_code == 200, registered.get_json()
        assert client.get("/api/auth/me").get_json() == {"user_id": user_id}

        # The link is single-use.
        assert client.post("/api/auth/register/options", json={"enrollment_token": token}).status_code == 400

        # Signed-in users can't read someone else's dashboard; their own passes
        # the guard (404 here only because this throwaway user has no plan).
        assert client.get("/api/users/someone_else/dashboard").status_code == 403
        assert client.get(f"/api/users/{user_id}/dashboard").status_code == 404

        assert client.post("/api/auth/logout").status_code == 204
        assert client.get("/api/auth/me").status_code == 401

        login_options = client.post("/api/auth/login/options").get_json()
        assertion = authenticator.assert_(login_options)
        signed_in = client.post("/api/auth/login/verify", json={"credential": assertion})
        assert signed_in.status_code == 200, signed_in.get_json()
        assert client.get("/api/auth/me").get_json() == {"user_id": user_id}

        # Replaying the same assertion fails — its challenge was consumed.
        assert client.post("/api/auth/login/verify", json={"credential": assertion}).status_code == 401

        # A signature from a different key is rejected.
        impostor = SoftwareAuthenticator()
        impostor.credential_id, impostor.user_handle = authenticator.credential_id, authenticator.user_handle
        forged = impostor.assert_(client.post("/api/auth/login/options").get_json())
        assert client.post("/api/auth/login/verify", json={"credential": forged}).status_code == 401
    finally:
        live_app.plan_repo.client.table("user_profiles").delete().eq("user_id", user_id).execute()
