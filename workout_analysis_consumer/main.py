"""Consumer for workout-complete-events -> Tanglish workout-day summary.

Run (from the repo root):  python3 -m workout_analysis_consumer.main
"""
import json
import logging

from workout_analysis_consumer.consumer import WORKOUT_COMPLETE_TOPIC, build_consumer
from workout_analysis_consumer.kafka_producer import KafkaProducerClient
from workout_analysis_consumer.repository import AnalysisRepository
from workout_analysis_consumer.summarizer import generate_workout_summary
from workout_analysis_consumer.voice import generate_voice_note

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

producer = KafkaProducerClient()


def _process_message(repo: AnalysisRepository, session_id: int, day_number: int) -> None:
    context = repo.fetch_context(session_id, day_number)
    if context is None:
        logger.warning(
            "No session found for session_id=%s; skipping day_number=%s", session_id, day_number
        )
        return

    analysis = generate_workout_summary(context)

    # Best-effort: a TTS/storage failure shouldn't discard the (costlier)
    # LLM-generated text analysis, so it's still saved with audio_url unset.
    try:
        audio_url = generate_voice_note(analysis, session_id, day_number)
    except Exception:
        logger.exception(
            "Failed to generate voice note for session_id=%s day_number=%s", session_id, day_number
        )
        audio_url = None

    repo.save_analysis(session_id, day_number, analysis, audio_url)
    logger.info("Stored analysis for session_id=%s day_number=%s", session_id, day_number)

    # Best-effort: the analysis is already durably saved, so a failure to
    # publish this notification shouldn't fail the whole message.
    try:
        producer.send_workout_analysis_complete_event(
            context["user_id"], session_id, day_number
        )
    except Exception:
        logger.exception(
            "Failed to publish workout-analysis-complete event for session_id=%s day_number=%s",
            session_id, day_number,
        )


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
