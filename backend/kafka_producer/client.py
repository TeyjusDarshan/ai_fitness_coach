import json
import logging
import os
from pathlib import Path

from confluent_kafka import Producer
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# The one topic the voice processor (voice_processor/main.py) listens to.
# Every event names the processor that handles it in `target`:
# - "summarizer": a shared workout ({session_id, phone_number})
# - "router": a WhatsApp voice note or text without a Session ID line
#   ({phone_number, whatsapp_message_id, type, text | media_id})
# - "diet": a food recording from the PWA ({meal_log_id})
# Keyed by the client, so one client's events stay in order. The consumer
# duplicates these names since it's deployed separately.
USER_CONVERSATION_TOPIC = "user-conversation"
TARGET_SUMMARIZER = "summarizer"
TARGET_ROUTER = "router"
TARGET_DIET = "diet"

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

    def send_user_conversation_event(self, target: str, payload: dict, key: str) -> bool:
        """Produce one user-conversation event ({"target": target, **payload})
        keyed by `key` (the client), and block until it's acked or fails.
        False if it wasn't delivered in time."""
        self._producer.produce(
            USER_CONVERSATION_TOPIC,
            key=str(key).encode("utf-8"),
            value=json.dumps({"target": target, **payload}).encode("utf-8"),
            callback=_delivery_callback,
        )
        # Low volume, so a synchronous flush is cheap and gives the caller a
        # delivery guarantee before returning.
        pending = self._producer.flush(timeout=10)
        if pending > 0:
            logger.error(
                "Kafka flush timed out with %d message(s) still undelivered", pending
            )
        return pending == 0
