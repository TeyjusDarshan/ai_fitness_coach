"""Consumer for workout-complete-events -> Tanglish workout-day summary.

Run (from the repo root):  python3 -m workout_analysis_consumer.main
"""
import json
import logging

from workout_analysis_consumer.consumer import WORKOUT_COMPLETE_TOPIC, build_consumer
from workout_analysis_consumer.repository import AnalysisRepository
from workout_analysis_consumer.summarizer import generate_workout_summary

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _process_message(repo: AnalysisRepository, session_id: int, day_number: int) -> None:
    context = repo.fetch_context(session_id, day_number)
    if context is None:
        logger.warning(
            "No session found for session_id=%s; skipping day_number=%s", session_id, day_number
        )
        return

    analysis = generate_workout_summary(context)
    repo.save_analysis(session_id, day_number, analysis)
    logger.info("Stored analysis for session_id=%s day_number=%s", session_id, day_number)


def run() -> None:
    consumer = build_consumer()
    repo = AnalysisRepository()
    consumer.subscribe([WORKOUT_COMPLETE_TOPIC])
    logger.info("Listening on topic=%s", WORKOUT_COMPLETE_TOPIC)

    try:
        while True:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                logger.error("Kafka consume error: %s", msg.error())
                continue

            # Best-effort: commit every message once attempted, success or
            # not, so one bad/unprocessable message can't wedge the
            # partition and block everything after it. Failures are logged
            # for manual follow-up rather than retried automatically.
            try:
                payload = json.loads(msg.value())
                _process_message(repo, payload["session_id"], payload["day_number"])
            except Exception:
                logger.exception(
                    "Failed to process message at offset=%s partition=%s",
                    msg.offset(), msg.partition(),
                )
            finally:
                consumer.commit(msg)
    finally:
        consumer.close()


if __name__ == "__main__":
    run()
