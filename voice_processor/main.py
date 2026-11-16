"""The voice processor: one Kafka consumer for every topic that carries a
client's voice, each handled its own way.

- workout-complete-events  -> workout.handle_workout_complete: summary,
  coach notes and clarifying questions for a shared workout
- workout-feedback-replies -> workout.handle_feedback_reply: her WhatsApp
  answers to those questions
- meal-log-events          -> diet tracking: a food recording turned into
  logged dishes with their ingredients (diet/pipeline.py)

Messages are handled one at a time, in the order they're polled.

Run (from the repo root):  python3 -m voice_processor.main
"""
import json
import logging
from typing import Any, Callable, Dict

logging.basicConfig(level=logging.INFO)

from diet.pipeline import process_meal_log  # noqa: E402
from diet.repository import DietRepository  # noqa: E402
from diet.transcription import transcribe_meal_log  # noqa: E402
from voice_processor import workout  # noqa: E402
from voice_processor.consumer import (  # noqa: E402
    FEEDBACK_REPLY_TOPIC,
    MEAL_LOG_TOPIC,
    WORKOUT_COMPLETE_TOPIC,
    build_consumer,
)
from voice_processor.repository import AnalysisRepository  # noqa: E402

logger = logging.getLogger(__name__)

Handler = Callable[[Dict[str, Any]], None]


def build_handlers(workout_repo: AnalysisRepository, diet_repo: DietRepository) -> Dict[str, Handler]:
    """topic -> what to do with one of its messages (the decoded payload)."""
    return {
        WORKOUT_COMPLETE_TOPIC: lambda payload: workout.handle_workout_complete(workout_repo, payload),
        FEEDBACK_REPLY_TOPIC: lambda payload: workout.handle_feedback_reply(workout_repo, payload),
        MEAL_LOG_TOPIC: lambda payload: process_meal_log(diet_repo, payload["meal_log_id"], transcribe_meal_log),
    }


def handle_message(handlers: Dict[str, Handler], topic: str, value: bytes) -> None:
    """Hand one message to its topic's handler. Never raises: a message that
    can't be handled is logged and skipped."""
    handler = handlers.get(topic)
    if handler is None:
        logger.error("No handler for topic=%s; skipping", topic)
        return
    try:
        handler(json.loads(value))
    except Exception:
        logger.exception("Failed to handle a message on topic=%s", topic)


def run() -> None:
    handlers = build_handlers(AnalysisRepository(), DietRepository())
    consumer = build_consumer()
    consumer.subscribe(list(handlers))
    logger.info("Listening on topics=%s", list(handlers))

    try:
        while True:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                logger.error("Kafka consume error: %s", msg.error())
                continue
            # Committed once attempted, success or not, so one bad message
            # can't wedge its partition and block everything after it.
            # Failures are logged for manual follow-up, not retried.
            try:
                handle_message(handlers, msg.topic(), msg.value())
            finally:
                consumer.commit(msg)
    finally:
        consumer.close()


if __name__ == "__main__":
    run()
