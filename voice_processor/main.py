"""The voice processor: one Kafka consumer on the `user-conversation` topic.
Every event names the processor that handles it in `target`
(voice_processor/processors.py):

- summarizer -> a shared workout: summary, coach notes and clarifying
  questions sent back as a voice note (workout.handle_workout_complete)
- router     -> a WhatsApp voice note or text: downloaded, transcribed and
  sorted by Claude Haiku into a question reply, a diet check-in or
  neither (router.handle_inbound)
- diet       -> a food recording from the PWA worked out into dishes
  (diet/pipeline.py)

Messages are handled one at a time, in the order they're polled.

Run (from the repo root):  python3 -m voice_processor.main
"""
import json
import logging
from typing import Dict

logging.basicConfig(level=logging.INFO)

from diet.repository import DietRepository  # noqa: E402
from voice_processor.consumer import USER_CONVERSATION_TOPIC, build_consumer  # noqa: E402
from voice_processor.processors import Processor, build_processors  # noqa: E402
from voice_processor.repository import AnalysisRepository  # noqa: E402

logger = logging.getLogger(__name__)


def handle_message(processors: Dict[str, Processor], value: bytes) -> None:
    """Hand one event to the processor its `target` names. Never raises: an
    event that can't be handled is logged and skipped."""
    try:
        payload = json.loads(value)
        target = payload.get("target")
        processor = processors.get(target)
        if processor is None:
            logger.error("No processor for target=%s; skipping", target)
            return
        processor.handle(payload)
    except Exception:
        logger.exception("Failed to handle a user-conversation event")


def run() -> None:
    processors = build_processors(AnalysisRepository(), DietRepository())
    consumer = build_consumer()
    consumer.subscribe([USER_CONVERSATION_TOPIC])
    logger.info("Listening on topic=%s for targets=%s", USER_CONVERSATION_TOPIC, list(processors))

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
                handle_message(processors, msg.value())
            finally:
                consumer.commit(msg)
    finally:
        consumer.close()


if __name__ == "__main__":
    run()
