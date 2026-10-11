"""Passkey (WebAuthn) enrollment and sign-in.

Flow: the coach mints a one-time enrollment link for an existing user
(POST /api/admin/users/<user_id>/enrollment-link); opening it runs
register/options -> the device's passkey prompt -> register/verify, which
stores the credential and signs the user in. Later sign-ins use
login/options -> passkey prompt -> login/verify with discoverable
credentials, so no username is typed.

Each /verify call finds its challenge by reading it back out of the
credential's clientDataJSON and atomically deleting the stored row, so a
challenge works at most once and no per-client server state is needed.
"""
import os
import secrets
from typing import Optional

from flask import Blueprint, Response, g, jsonify, make_response, request
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url, parse_client_data_json
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    COSEAlgorithmIdentifier,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from backend.auth import (
    CHALLENGE_TTL,
    ENROLLMENT_TTL,
    SESSION_COOKIE,
    allowed_origins,
    auth_repo,
    clear_session_cookie,
    current_user_id,
    hash_token,
    require_admin,
    require_auth,
    rp_id,
    rp_name,
    start_session,
    utcnow,
)

auth_bp = Blueprint("auth", __name__)

SUPPORTED_ALGS = [
    COSEAlgorithmIdentifier.ECDSA_SHA_256,
    COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256,
]

# Malformed client payloads surface as any of these from py_webauthn's parsers.
_BAD_CREDENTIAL_ERRORS = (WebAuthnException, KeyError, ValueError, TypeError)

INVALID_LINK_MESSAGE = "This sign-up link is invalid or has expired. Ask your coach for a new one."


def _client_challenge(credential: dict) -> Optional[str]:
    try:
        client_data = parse_client_data_json(
            base64url_to_bytes(credential["response"]["clientDataJSON"])
        )
    except _BAD_CREDENTIAL_ERRORS:
        return None
    return bytes_to_base64url(client_data.challenge)


def _registering_user(body: dict):
    """(user_id, error_response) for a registration request — via the
    enrollment token in the body, or else the signed-in user adding
    another device."""
    token = body.get("enrollment_token")
    if token:
        row = auth_repo.get_valid_enrollment_token(hash_token(token))
        if row is None:
            return None, (jsonify({"error": INVALID_LINK_MESSAGE}), 400)
        return row["user_id"], None
    user_id = current_user_id()
    if user_id is None:
        return None, (jsonify({"error": "Not signed in."}), 401)
    return user_id, None


def _json_options(options) -> Response:
    return Response(options_to_json(options), mimetype="application/json")


@auth_bp.post("/api/admin/users/<user_id>/enrollment-link")
@require_admin
def create_enrollment_link(user_id):
    if auth_repo.get_user_auth_row(user_id) is None:
        return jsonify({"error": f"User {user_id} not found."}), 404

    token = secrets.token_urlsafe(32)
    expires_at = utcnow() + ENROLLMENT_TTL
    auth_repo.create_enrollment_token(user_id, hash_token(token), expires_at)

    base_url = os.environ.get("APP_BASE_URL", request.host_url).rstrip("/")
    return jsonify({
        "url": f"{base_url}/enroll?token={token}",
        "expires_at": expires_at.isoformat(),
    }), 200


@auth_bp.post("/api/auth/register/options")
def registration_options():
    body = request.get_json(silent=True) or {}
    user_id, error = _registering_user(body)
    if error:
        return error

    user_handle = auth_repo.get_or_create_user_handle(user_id)
    options = generate_registration_options(
        rp_id=rp_id(),
        rp_name=rp_name(),
        user_id=base64url_to_bytes(user_handle),
        user_name=user_id,
        user_display_name=user_id,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        supported_pub_key_algs=SUPPORTED_ALGS,
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(credential_id))
            for credential_id in auth_repo.list_credential_ids(user_id)
        ],
    )
    auth_repo.create_challenge(
        bytes_to_base64url(options.challenge), "registration", user_id, utcnow() + CHALLENGE_TTL
    )
    return _json_options(options)


@auth_bp.post("/api/auth/register/verify")
def registration_verify():
    body = request.get_json(silent=True) or {}
    credential = body.get("credential")
    if not isinstance(credential, dict):
        return jsonify({"error": "'credential' is required."}), 400

    user_id, error = _registering_user(body)
    if error:
        return error

    challenge = _client_challenge(credential)
    stored = auth_repo.consume_challenge(challenge, "registration") if challenge else None
    if stored is None or stored["user_id"] != user_id:
        return jsonify({"error": "Passkey setup expired. Please try again."}), 400

    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=rp_id(),
            expected_origin=allowed_origins(),
            require_user_verification=True,
            supported_pub_key_algs=SUPPORTED_ALGS,
        )
    except _BAD_CREDENTIAL_ERRORS:
        return jsonify({"error": "Could not verify this passkey."}), 400

    token = body.get("enrollment_token")
    if token and not auth_repo.consume_enrollment_token(hash_token(token)):
        return jsonify({"error": INVALID_LINK_MESSAGE}), 400

    credential_id = bytes_to_base64url(verified.credential_id)
    if auth_repo.get_passkey(credential_id) is not None:
        return jsonify({"error": "This passkey is already registered."}), 409

    auth_repo.add_passkey({
        "user_id": user_id,
        "credential_id": credential_id,
        "public_key": bytes_to_base64url(verified.credential_public_key),
        "sign_count": verified.sign_count,
        "transports": credential["response"].get("transports") or [],
        "aaguid": verified.aaguid,
        "backed_up": verified.credential_backed_up,
    })

    response = jsonify({"user_id": user_id})
    start_session(response, user_id)
    return response, 200


@auth_bp.post("/api/auth/login/options")
def authentication_options():
    auth_repo.delete_expired_challenges()
    options = generate_authentication_options(
        rp_id=rp_id(),
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    auth_repo.create_challenge(
        bytes_to_base64url(options.challenge), "authentication", None, utcnow() + CHALLENGE_TTL
    )
    return _json_options(options)


@auth_bp.post("/api/auth/login/verify")
def authentication_verify():
    failed = jsonify({"error": "Sign-in failed. Please try again."}), 401

    body = request.get_json(silent=True) or {}
    credential = body.get("credential")
    if not isinstance(credential, dict) or not isinstance(credential.get("id"), str):
        return failed

    challenge = _client_challenge(credential)
    if not challenge or auth_repo.consume_challenge(challenge, "authentication") is None:
        return failed

    passkey = auth_repo.get_passkey(credential["id"])
    if passkey is None:
        return failed

    profile = auth_repo.get_user_auth_row(passkey["user_id"])
    user_handle = (credential.get("response") or {}).get("userHandle")
    if profile is None or user_handle != profile["webauthn_user_handle"]:
        return failed

    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=rp_id(),
            expected_origin=allowed_origins(),
            credential_public_key=base64url_to_bytes(passkey["public_key"]),
            credential_current_sign_count=passkey["sign_count"],
            require_user_verification=True,
        )
    except _BAD_CREDENTIAL_ERRORS:
        return failed

    auth_repo.update_passkey_usage(passkey["credential_id"], verified.new_sign_count)

    response = jsonify({"user_id": passkey["user_id"]})
    start_session(response, passkey["user_id"])
    return response, 200


@auth_bp.get("/api/auth/me")
@require_auth
def me():
    auth_repo.touch_session(hash_token(request.cookies[SESSION_COOKIE]))
    return jsonify({"user_id": g.user_id}), 200


@auth_bp.post("/api/auth/logout")
def logout():
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        auth_repo.delete_session(hash_token(token))
    response = make_response("", 204)
    clear_session_cookie(response)
    return response
