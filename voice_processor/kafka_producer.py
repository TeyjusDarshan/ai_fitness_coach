import json
import logging
import os
from pathlib import Path

from confluent_kafka import Producer
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

WORKOUT_ANALYSIS_COMPLETE_TOPIC = "workout-analysis-complete"

_DEFAULT_CA_CERT_PATH = Path(__file__).resolve().parent / "certs" / "ca.pem"


def _delivery_callback(err, msg):
    if err is not None:
        logger.error("Kafka delivery failed for topic %s: %s", msg.topic(), err)
    else:
        logger.debug(
            "Kafka delivery succeeded: topic=%s partition=%s offset=%s",
            msg.topic(), msg.partition(), msg.offset(),
        )


class KafkaProducerClient:
    """Producer client for the Aiven-hosted Kafka cluster (same SASL_SSL/
    SCRAM-SHA-256 auth as consumer.py / backend/kafka_producer/client.py).
    """

    def __init__(self):
        self._producer = Producer({
            "bootstrap.servers": os.environ["KAFKA_BOOTSTRAP_SERVERS"],
            "security.protocol": "SASL_SSL",
            "sasl.mechanism": "SCRAM-SHA-256",
            "sasl.username": os.environ["KAFKA_USERNAME"],
            "sasl.password": os.environ["KAFKA_PASSWORD"],
            "ssl.ca.location": os.getenv("KAFKA_CA_CERT_PATH", str(_DEFAULT_CA_CERT_PATH)),
        })

    def send_workout_analysis_complete_event(
        self, user_id: str, session_id: int, day_number: int
    ) -> None:
        """Produce a workout-analysis-complete event and block until it's acked or fails."""
        payload = {"user_id": user_id, "session_id": session_id, "day_number": day_number}
        self._producer.produce(
            WORKOUT_ANALYSIS_COMPLETE_TOPIC,
            value=json.dumps(payload).encode("utf-8"),
            callback=_delivery_callback,
        )
        # Low volume (one event per analyzed day) so a synchronous flush is
        # cheap and gives the caller a delivery guarantee before returning.
        pending = self._producer.flush(timeout=10)
        if pending > 0:
            logger.error(
                "Kafka flush timed out with %d message(s) still undelivered", pending
            )
