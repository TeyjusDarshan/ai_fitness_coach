"""Consumer for meal-log-events: one event per meal recording, turned into
logged items (see diet/pipeline.py).

Its own process and consumer group, apart from workout_analysis_consumer,
so a workout analysis that takes minutes never keeps a client waiting on
the "working it out" screen.

Run (from the repo root):  python3 -m diet.consumer
"""
import json
import logging
import os

from diet.pipeline import process_meal_log
from diet.repository import DietRepository
from diet.transcription import transcribe_meal_log
from workout_analysis_consumer.consumer import build_consumer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Must match backend/kafka_producer/client.py's MEAL_LOG_TOPIC.
MEAL_LOG_TOPIC = "meal-log-events"
DEFAULT_GROUP_ID = "meal-log-consumer"


def run() -> None:
    consumer = build_consumer(os.getenv("MEAL_LOG_CONSUMER_GROUP_ID", DEFAULT_GROUP_ID))
    repo = DietRepository()
    consumer.subscribe([MEAL_LOG_TOPIC])
    logger.info("Listening on topic=%s", MEAL_LOG_TOPIC)

    try:
        while True:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                logger.error("Kafka consume error: %s", msg.error())
                continue
            # Committed once attempted, success or not (process_meal_log
            # marks a log it couldn't handle as failed), so one bad message
            # can't block the ones after it.
            try:
                process_meal_log(repo, json.loads(msg.value())["meal_log_id"], transcribe_meal_log)
            except Exception:
                logger.exception("Failed to process message at offset=%s partition=%s", msg.offset(), msg.partition())
            finally:
                consumer.commit(msg)
    finally:
        consumer.close()


if __name__ == "__main__":
    run()
