import json
import logging
import os
from pathlib import Path

from confluent_kafka import Producer
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

WORKOUT_COMPLETE_TOPIC = "workout-complete-events"

# backend/kafka_producer/client.py -> backend/certs/ca.pem
_DEFAULT_CA_CERT_PATH = Path(__file__).resolve().parent.parent / "certs" / "ca.pem"


def _delivery_callback(err, msg):
    if err is not None:
        logger.error("Kafka delivery failed for topic %s: %s", msg.topic(), err)
    else:
        logger.debug(
            "Kafka delivery succeeded: topic=%s partition=%s offset=%s",
            msg.topic(), msg.partition(), msg.offset(),
        )


class KafkaProducerClient:
    """Producer client for the Aiven-hosted Kafka cluster.

    Auth is SASL_SSL/SCRAM-SHA-256 (Aiven's username+password scheme, not
    mutual TLS) since only a CA cert plus username/password were provisioned,
    no client cert/key.
    """

    def __init__(self):
        bootstrap_servers = os.environ["KAFKA_BOOTSTRAP_SERVERS"]
        username = os.environ["KAFKA_USERNAME"]
        password = os.environ["KAFKA_PASSWORD"]
        ca_cert_path = os.getenv("KAFKA_CA_CERT_PATH", str(_DEFAULT_CA_CERT_PATH))

        self._producer = Producer({
            "bootstrap.servers": bootstrap_servers,
            "security.protocol": "SASL_SSL",
            "sasl.mechanism": "SCRAM-SHA-256",
            "sasl.username": username,
            "sasl.password": password,
            "ssl.ca.location": ca_cert_path,
        })

    def send_workout_complete_event(self, session_id: int, day_number: int, phone_number: str) -> None:
        """Produce a workout-complete event and block until it's acked or fails."""
        payload = {"session_id": session_id, "day_number": day_number, "phone_number": phone_number}
        self._producer.produce(
            WORKOUT_COMPLETE_TOPIC,
            value=json.dumps(payload).encode("utf-8"),
            callback=_delivery_callback,
        )
        # Low volume (one event per completed day) so a synchronous flush is
        # cheap and gives the caller a delivery guarantee before returning.
        pending = self._producer.flush(timeout=10)
        if pending > 0:
            logger.error(
                "Kafka flush timed out with %d message(s) still undelivered", pending
            )
