"""Tests for the passkey endpoints in backend/controllers/auth_controller.py.

The cryptographic checks (py_webauthn's verify_registration_response /
verify_authentication_response) are stubbed — they're py_webauthn's job and
need a real authenticator to exercise. Everything around them runs for real:
challenge extraction from clientDataJSON, single-use challenge/token
handling, user-handle matching, and the session cookie.
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.exceptions import InvalidAuthenticationResponse

ADMIN_KEY = "test-admin-key"
CHALLENGE = bytes_to_base64url(b"server-challenge-bytes")
USER_HANDLE = bytes_to_base64url(b"random-user-handle")


@pytest.fixture
def env(app_module, monkeypatch):
    """(client, auth module, controller module) with every AuthRepository
    method replaced by a MagicMock the test can configure."""
    import backend.auth as auth
    import backend.controllers.auth_controller as controller

    monkeypatch.setenv("ADMIN_API_KEY", ADMIN_KEY)
    monkeypatch.setenv("APP_BASE_URL", "https://coach.example.com")
    for name in (
        "get_user_auth_row", "get_or_create_user_handle", "create_challenge", "consume_challenge",
        "delete_expired_challenges", "create_session", "get_active_session", "touch_session",
        "delete_session", "list_credential_ids", "get_passkey", "add_passkey",
        "update_passkey_usage", "create_enrollment_token", "get_valid_enrollment_token",
        "consume_enrollment_token",
    ):
        monkeypatch.setattr(auth.auth_repo, name, MagicMock())
    auth.auth_repo.get_user_auth_row.return_value = {"user_id": "usr_1", "name": "Asha", "webauthn_user_handle": None}
    return app_module.app.test_client(), auth, controller


def _credential(kind="webauthn.create", challenge=CHALLENGE, **response_extra):
    client_data = {"type": kind, "challenge": challenge, "origin": "http://localhost:5173"}
    return {
        "id": "cred-1",
        "rawId": "cred-1",
        "type": "public-key",
        "response": {
            "clientDataJSON": bytes_to_base64url(json.dumps(client_data).encode()),
            **response_extra,
        },
    }


def _session_cookie(response):
    return next((c for c in response.headers.getlist("Set-Cookie") if c.startswith("fc_session=")), None)


# --- enrollment link ---------------------------------------------------------

def test_enrollment_link_requires_admin_key(env):
    client, auth, _ = env
    assert client.post("/api/admin/users/usr_1/enrollment-link").status_code == 401
    auth.auth_repo.create_enrollment_token.assert_not_called()


def test_enrollment_link_unknown_user_is_404(env):
    client, auth, _ = env
    auth.auth_repo.get_user_auth_row.return_value = None

    response = client.post("/api/admin/users/nobody/enrollment-link", headers={"X-Admin-Key": ADMIN_KEY})

    assert response.status_code == 404


def test_enrollment_link_stores_only_the_token_hash(env):
    client, auth, _ = env
    auth.auth_repo.get_user_auth_row.return_value = {"user_id": "usr_1", "name": "Asha", "webauthn_user_handle": None}

    response = client.post("/api/admin/users/usr_1/enrollment-link", headers={"X-Admin-Key": ADMIN_KEY})

    assert response.status_code == 200
    url = response.get_json()["url"]
    assert url.startswith("https://coach.example.com/enroll?token=")
    token = url.split("token=", 1)[1]
    user_id, stored_hash, _ = auth.auth_repo.create_enrollment_token.call_args.args
    assert user_id == "usr_1"
    assert stored_hash == auth.hash_token(token) != token


# --- registration ------------------------------------------------------------

def test_register_options_rejects_invalid_enrollment_token(env):
    client, auth, _ = env
    auth.auth_repo.get_valid_enrollment_token.return_value = None

    response = client.post("/api/auth/register/options", json={"enrollment_token": "bogus"})

    assert response.status_code == 400
    auth.auth_repo.create_challenge.assert_not_called()


def test_register_options_without_token_or_session_is_401(env):
    client, _, _ = env
    assert client.post("/api/auth/register/options", json={}).status_code == 401


def test_register_options_returns_options_and_stores_challenge(env):
    client, auth, _ = env
    auth.auth_repo.get_valid_enrollment_token.return_value = {"user_id": "usr_1"}
    auth.auth_repo.get_or_create_user_handle.return_value = USER_HANDLE
    existing_credential_id = bytes_to_base64url(b"existing-cred")
    auth.auth_repo.list_credential_ids.return_value = [existing_credential_id]

    response = client.post("/api/auth/register/options", json={"enrollment_token": "tok"})

    assert response.status_code == 200
    options = response.get_json()
    assert options["rp"]["id"] == "localhost"
    assert options["user"]["id"] == USER_HANDLE
    assert options["authenticatorSelection"]["residentKey"] == "required"
    assert options["authenticatorSelection"]["userVerification"] == "required"
    assert [c["id"] for c in options["excludeCredentials"]] == [existing_credential_id]
    challenge, purpose, user_id, _ = auth.auth_repo.create_challenge.call_args.args
    assert (challenge, purpose, user_id) == (options["challenge"], "registration", "usr_1")


def test_register_verify_success_stores_passkey_and_signs_in(env, monkeypatch):
    client, auth, controller = env
    auth.auth_repo.get_valid_enrollment_token.return_value = {"user_id": "usr_1"}
    auth.auth_repo.consume_challenge.return_value = {"user_id": "usr_1"}
    auth.auth_repo.consume_enrollment_token.return_value = True
    auth.auth_repo.get_passkey.return_value = None
    monkeypatch.setattr(controller, "verify_registration_response", MagicMock(return_value=SimpleNamespace(
        credential_id=b"cred-bytes", credential_public_key=b"public-key", sign_count=0,
        aaguid="00000000-0000-0000-0000-000000000000", credential_backed_up=True,
    )))

    response = client.post("/api/auth/register/verify", json={
        "enrollment_token": "tok",
        "credential": _credential(transports=["internal", "hybrid"]),
    })

    assert response.status_code == 200
    assert response.get_json() == {"user_id": "usr_1", "name": "Asha", "gender": None}
    auth.auth_repo.consume_challenge.assert_called_once_with(CHALLENGE, "registration")
    stored = auth.auth_repo.add_passkey.call_args.args[0]
    assert stored["user_id"] == "usr_1"
    assert stored["credential_id"] == bytes_to_base64url(b"cred-bytes")
    assert stored["public_key"] == bytes_to_base64url(b"public-key")
    assert stored["transports"] == ["internal", "hybrid"]
    cookie = _session_cookie(response)
    assert cookie and "HttpOnly" in cookie and "SameSite=Lax" in cookie and "Path=/api" in cookie


def test_register_verify_rejects_expired_or_reused_challenge(env, monkeypatch):
    client, auth, controller = env
    auth.auth_repo.get_valid_enrollment_token.return_value = {"user_id": "usr_1"}
    auth.auth_repo.consume_challenge.return_value = None
    monkeypatch.setattr(controller, "verify_registration_response", MagicMock())

    response = client.post("/api/auth/register/verify", json={"enrollment_token": "tok", "credential": _credential()})

    assert response.status_code == 400
    controller.verify_registration_response.assert_not_called()
    auth.auth_repo.add_passkey.assert_not_called()


def test_register_verify_rejects_challenge_issued_to_another_user(env, monkeypatch):
    client, auth, controller = env
    auth.auth_repo.get_valid_enrollment_token.return_value = {"user_id": "usr_1"}
    auth.auth_repo.consume_challenge.return_value = {"user_id": "usr_2"}
    monkeypatch.setattr(controller, "verify_registration_response", MagicMock())

    response = client.post("/api/auth/register/verify", json={"enrollment_token": "tok", "credential": _credential()})

    assert response.status_code == 400
    controller.verify_registration_response.assert_not_called()


def test_register_verify_rejects_already_used_enrollment_token(env, monkeypatch):
    client, auth, controller = env
    auth.auth_repo.get_valid_enrollment_token.return_value = {"user_id": "usr_1"}
    auth.auth_repo.consume_challenge.return_value = {"user_id": "usr_1"}
    auth.auth_repo.consume_enrollment_token.return_value = False
    monkeypatch.setattr(controller, "verify_registration_response", MagicMock(return_value=SimpleNamespace(
        credential_id=b"c", credential_public_key=b"k", sign_count=0, aaguid="", credential_backed_up=False,
    )))

    response = client.post("/api/auth/register/verify", json={"enrollment_token": "tok", "credential": _credential()})

    assert response.status_code == 400
    auth.auth_repo.add_passkey.assert_not_called()
    assert _session_cookie(response) is None


# --- sign-in -----------------------------------------------------------------

def _login_credential(user_handle=USER_HANDLE):
    return _credential(kind="webauthn.get", userHandle=user_handle, authenticatorData="", signature="")


def _known_passkey(auth):
    auth.auth_repo.consume_challenge.return_value = {"user_id": None}
    auth.auth_repo.get_passkey.return_value = {
        "user_id": "usr_1", "credential_id": "cred-1",
        "public_key": bytes_to_base64url(b"public-key"), "sign_count": 0,
    }
    auth.auth_repo.get_user_auth_row.return_value = {"user_id": "usr_1", "name": "Asha", "webauthn_user_handle": USER_HANDLE}


def test_login_options_are_discoverable_and_store_challenge(env):
    client, auth, _ = env

    response = client.post("/api/auth/login/options")

    assert response.status_code == 200
    options = response.get_json()
    assert options.get("allowCredentials", []) == []
    assert options["userVerification"] == "required"
    auth.auth_repo.delete_expired_challenges.assert_called_once()
    challenge, purpose, user_id, _ = auth.auth_repo.create_challenge.call_args.args
    assert (challenge, purpose, user_id) == (options["challenge"], "authentication", None)


def test_login_verify_success_updates_sign_count_and_signs_in(env, monkeypatch):
    client, auth, controller = env
    _known_passkey(auth)
    monkeypatch.setattr(
        controller, "verify_authentication_response", MagicMock(return_value=SimpleNamespace(new_sign_count=0))
    )

    response = client.post("/api/auth/login/verify", json={"credential": _login_credential()})

    assert response.status_code == 200
    assert response.get_json() == {"user_id": "usr_1", "name": "Asha", "gender": None}
    auth.auth_repo.consume_challenge.assert_called_once_with(CHALLENGE, "authentication")
    auth.auth_repo.update_passkey_usage.assert_called_once_with("cred-1", 0)
    assert _session_cookie(response) is not None


def test_login_verify_unknown_credential_is_401(env, monkeypatch):
    client, auth, controller = env
    _known_passkey(auth)
    auth.auth_repo.get_passkey.return_value = None
    monkeypatch.setattr(controller, "verify_authentication_response", MagicMock())

    response = client.post("/api/auth/login/verify", json={"credential": _login_credential()})

    assert response.status_code == 401
    controller.verify_authentication_response.assert_not_called()


def test_login_verify_rejects_mismatched_user_handle(env, monkeypatch):
    client, auth, controller = env
    _known_passkey(auth)
    monkeypatch.setattr(controller, "verify_authentication_response", MagicMock())

    response = client.post(
        "/api/auth/login/verify", json={"credential": _login_credential(user_handle="someone-else")}
    )

    assert response.status_code == 401
    controller.verify_authentication_response.assert_not_called()


def test_login_verify_bad_signature_is_401(env, monkeypatch):
    client, auth, controller = env
    _known_passkey(auth)
    monkeypatch.setattr(
        controller, "verify_authentication_response",
        MagicMock(side_effect=InvalidAuthenticationResponse("bad signature")),
    )

    response = client.post("/api/auth/login/verify", json={"credential": _login_credential()})

    assert response.status_code == 401
    auth.auth_repo.update_passkey_usage.assert_not_called()
    assert _session_cookie(response) is None


def test_login_verify_rejects_expired_challenge(env, monkeypatch):
    client, auth, controller = env
    _known_passkey(auth)
    auth.auth_repo.consume_challenge.return_value = None
    monkeypatch.setattr(controller, "verify_authentication_response", MagicMock())

    response = client.post("/api/auth/login/verify", json={"credential": _login_credential()})

    assert response.status_code == 401
    controller.verify_authentication_response.assert_not_called()


# --- me / logout -------------------------------------------------------------

def test_me_without_cookie_is_401(env):
    client, _, _ = env
    assert client.get("/api/auth/me").status_code == 401


def test_me_returns_signed_in_user(env):
    client, auth, _ = env
    auth.auth_repo.get_active_session.return_value = {"user_id": "usr_1"}
    client.set_cookie(auth.SESSION_COOKIE, "tok", path="/api")

    response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.get_json() == {"user_id": "usr_1", "name": "Asha", "gender": None}
    auth.auth_repo.get_active_session.assert_called_once_with(auth.hash_token("tok"))


def test_logout_deletes_session_and_clears_cookie(env):
    client, auth, _ = env
    client.set_cookie(auth.SESSION_COOKIE, "tok", path="/api")

    response = client.post("/api/auth/logout")

    assert response.status_code == 204
    auth.auth_repo.delete_session.assert_called_once_with(auth.hash_token("tok"))
    cookie = _session_cookie(response)
    assert cookie and ("Max-Age=0" in cookie or "Expires=Thu, 01 Jan 1970" in cookie)
