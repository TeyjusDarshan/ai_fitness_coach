"""Integration test for KafkaProducerClient against the real Aiven cluster.

No mocking: this produces a real message via send_workout_complete_event and
consumes it back from the real workout-complete-events topic, using the same
credentials/CA cert as the app (backend/kafka_producer/client.py, .env).
Requires network access to the Aiven-hosted broker.
"""
import json
import os
import time
import uuid

import pytest
from confluent_kafka import Consumer

from backend.kafka_producer import KafkaProducerClient, WORKOUT_COMPLETE_TOPIC
from backend.kafka_producer.client import _DEFAULT_CA_CERT_PATH

POLL_TIMEOUT_SECONDS = 20


def _make_consumer() -> Consumer:
    return Consumer({
        "bootstrap.servers": os.environ["KAFKA_BOOTSTRAP_SERVERS"],
        "security.protocol": "SASL_SSL",
        "sasl.mechanism": "SCRAM-SHA-256",
        "sasl.username": os.environ["KAFKA_USERNAME"],
        "sasl.password": os.environ["KAFKA_PASSWORD"],
        "ssl.ca.location": os.getenv("KAFKA_CA_CERT_PATH", str(_DEFAULT_CA_CERT_PATH)),
        # Fresh group per test run so there's no committed offset to race
        # against, and we can safely read from the beginning of the topic.
        "group.id": f"kafka-producer-integration-test-{uuid.uuid4()}",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })


@pytest.mark.integration
def test_send_workout_complete_event_is_consumable():
    # Random sentinel values so this run's message is unambiguously
    # identifiable among whatever else is already on the topic.
    session_id = uuid.uuid4().int % 1_000_000_000
    day_number = uuid.uuid4().int % 1_000_000_000
    phone_number = "919876543210"

    producer = KafkaProducerClient()
    producer.send_workout_complete_event(session_id, day_number, phone_number)

    consumer = _make_consumer()
    try:
        consumer.subscribe([WORKOUT_COMPLETE_TOPIC])

        deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
        found_payload = None
        while time.monotonic() < deadline and found_payload is None:
            msg = consumer.poll(timeout=1.0)
            if msg is None or msg.error():
                continue
            payload = json.loads(msg.value())
            if payload.get("session_id") == session_id and payload.get("day_number") == day_number:
                found_payload = payload
                print("Found Payload", found_payload)

    finally:
        consumer.close()


    assert found_payload == {
        "session_id": session_id, "day_number": day_number, "phone_number": phone_number,
    }
