import sys
from unittest.mock import MagicMock, patch

import pytest

# Modules that build a Supabase-backed repository at import time; dropped
# from sys.modules around each test so every test imports them fresh under
# the mocked create_client instead of reusing a previous test's instances.
_APP_MODULES = (
    "backend.app",
    "backend.auth",
    "backend.controllers.auth_controller",
    "backend.controllers.admin_plan_controller",
)

TEST_SESSION_TOKEN = "test-session-token"


def _drop_app_modules():
    for name in _APP_MODULES:
        sys.modules.pop(name, None)


@pytest.fixture
def app_module():
    """Import backend.app with the Supabase, Kafka, and WhatsApp clients mocked out.

    backend.app instantiates WorkoutPlanRepository() (and, via backend.auth,
    AuthRepository()), and (via whatsapp_webhook_controller)
    KafkaProducerClient() and WhatsAppClient(), at module import time, and
    each would otherwise open a real connection or require real creds from
    .env. Patch the underlying client constructors before the first import
    so none ever talks to a real service, then drop the cached modules
    afterwards so the next test gets the same treatment.
    """
    _drop_app_modules()
    with patch("backend.repository.workout_plan_repository.create_client", return_value=MagicMock()), \
         patch("backend.repository.auth_repository.create_client", return_value=MagicMock()), \
         patch("backend.repository.workout_repository.create_client", return_value=MagicMock()), \
         patch("backend.kafka_producer.client.Producer", return_value=MagicMock()), \
         patch("whatsapp_client.client.WhatsAppClient.__init__", return_value=None):
        import backend.app as module
        module.app.config.update(TESTING=True)
        yield module
    _drop_app_modules()


@pytest.fixture
def sign_in(app_module, monkeypatch):
    """Return a test client signed in as the given user_id.

    Stubs the session lookup rather than the auth guard itself, so
    require_auth's real cookie handling still runs.
    """
    import backend.auth as auth

    def _sign_in(user_id):
        monkeypatch.setattr(
            auth.auth_repo,
            "get_active_session",
            MagicMock(return_value={"user_id": user_id, "expires_at": "2999-01-01T00:00:00+00:00"}),
        )
        client = app_module.app.test_client()
        client.set_cookie(auth.SESSION_COOKIE, TEST_SESSION_TOKEN, path="/api")
        return client

    return _sign_in
