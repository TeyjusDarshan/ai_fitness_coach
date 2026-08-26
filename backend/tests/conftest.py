import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def app_module():
    """Import backend.app with the Supabase and Kafka clients mocked out.

    backend.app instantiates WorkoutPlanRepository() and KafkaProducerClient()
    at module import time, and each would otherwise open a real connection
    (Supabase client / Kafka producer, both reading real creds from .env).
    Patch the underlying client constructors before the first import so
    neither ever talks to a real service, then drop the cached module
    afterwards so the next test gets the same treatment.
    """
    sys.modules.pop("backend.app", None)
    with patch("backend.repository.workout_plan_repository.create_client", return_value=MagicMock()), \
         patch("backend.kafka_producer.client.Producer", return_value=MagicMock()):
        import backend.app as module
        module.app.config.update(TESTING=True)
        yield module
    sys.modules.pop("backend.app", None)
