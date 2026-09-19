import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def app_module():
    """Import backend.app with the Supabase, Kafka, and WhatsApp clients mocked out.

    backend.app instantiates WorkoutPlanRepository(), KafkaProducerClient(),
    and (via whatsapp_webhook_controller) WhatsAppClient() at module import
    time, and each would otherwise open a real connection or require real
    creds from .env. Patch the underlying client constructors before the
    first import so none ever talks to a real service, then drop the cached
    module afterwards so the next test gets the same treatment.
    """
    sys.modules.pop("backend.app", None)
    with patch("backend.repository.workout_plan_repository.create_client", return_value=MagicMock()), \
         patch("backend.kafka_producer.client.Producer", return_value=MagicMock()), \
         patch("backend.clients.whatsapp_client.WhatsAppClient.__init__", return_value=None):
        import backend.app as module
        module.app.config.update(TESTING=True)
        yield module
    sys.modules.pop("backend.app", None)
