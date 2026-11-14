import os
from pathlib import Path

from confluent_kafka import Consumer
from dotenv import load_dotenv

load_dotenv()

# Must match backend/kafka_producer/client.py's WORKOUT_COMPLETE_TOPIC — this
# package is deployed independently of backend, so the topic name is
# duplicated rather than imported.
WORKOUT_COMPLETE_TOPIC = "workout-complete-events"

# Must match backend/kafka_producer/client.py's FEEDBACK_REPLY_TOPIC: the
# client's WhatsApp replies to the clarifying questions.
FEEDBACK_REPLY_TOPIC = "workout-feedback-replies"

DEFAULT_CONSUMER_GROUP_ID = "workout-analysis-consumer"

_DEFAULT_CA_CERT_PATH = Path(__file__).resolve().parent / "certs" / "ca.pem"


def build_consumer() -> Consumer:
    """Consumer for the Aiven-hosted Kafka cluster (same SASL_SSL/SCRAM-SHA-256
    auth as backend/kafka_producer/client.py).

    enable.auto.commit is off: main.py commits each message explicitly after
    attempting to process it, once per message regardless of outcome, so a
    single unprocessable message can't wedge the partition and block
    everything after it. auto.offset.reset=earliest so a fresh deployment
    processes any backlog rather than silently skipping it.
    """
    return Consumer({
        "bootstrap.servers": os.environ["KAFKA_BOOTSTRAP_SERVERS"],
        "security.protocol": "SASL_SSL",
        "sasl.mechanism": "SCRAM-SHA-256",
        "sasl.username": os.environ["KAFKA_USERNAME"],
        "sasl.password": os.environ["KAFKA_PASSWORD"],
        "ssl.ca.location": os.getenv("KAFKA_CA_CERT_PATH", str(_DEFAULT_CA_CERT_PATH)),
        "group.id": os.getenv("KAFKA_CONSUMER_GROUP_ID", DEFAULT_CONSUMER_GROUP_ID),
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
        # One workout-complete message can run several STT jobs (up to
        # STT_JOB_TIMEOUT_SECONDS each) plus two Claude calls, which can
        # outlast the 300 s default before the next poll.
        "max.poll.interval.ms": int(os.getenv("KAFKA_MAX_POLL_INTERVAL_MS", "900000")),
    })
