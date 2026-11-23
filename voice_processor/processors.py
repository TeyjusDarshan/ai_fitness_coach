"""The voice processor's processors, one per `target` on the
user-conversation topic. Each takes one decoded event (`handle(payload)`);
which one runs is decided by code — the webhook's rule for `summarizer`,
the PWA for `diet`, and the router (Claude Haiku picks a label, code acts
on it) for everything else sent on WhatsApp.
"""
from typing import Any, Dict, Protocol

from diet.pipeline import process_meal_log
from diet.repository import DietRepository
from diet.transcription import transcribe_meal_log
from voice_processor import router, workout
from voice_processor.consumer import TARGET_DIET, TARGET_ROUTER, TARGET_SUMMARIZER
from voice_processor.repository import AnalysisRepository


class Processor(Protocol):
    def handle(self, payload: Dict[str, Any]) -> None: ...


class SummarizerProcessor:
    """A shared workout ({session_id, phone_number}) -> the analysis voice
    note with its clarifying questions."""

    def __init__(self, workout_repo: AnalysisRepository):
        self.workout_repo = workout_repo

    def handle(self, payload: Dict[str, Any]) -> None:
        workout.handle_workout_complete(self.workout_repo, payload)


class DietProcessor:
    """A food recording from the PWA ({meal_log_id}): transcribed from the
    voice-feedback bucket and worked out into dishes."""

    def __init__(self, diet_repo: DietRepository):
        self.diet_repo = diet_repo

    def handle(self, payload: Dict[str, Any]) -> None:
        process_meal_log(self.diet_repo, payload["meal_log_id"], transcribe_meal_log)


class RouterProcessor:
    """A WhatsApp voice note or text ({phone_number, whatsapp_message_id,
    type, text | media_id}) -> question reply, diet check-in or nothing."""

    def __init__(self, workout_repo: AnalysisRepository, diet_repo: DietRepository):
        self.workout_repo = workout_repo
        self.diet_repo = diet_repo

    def handle(self, payload: Dict[str, Any]) -> None:
        router.handle_inbound(self.workout_repo, self.diet_repo, payload)


def build_processors(workout_repo: AnalysisRepository, diet_repo: DietRepository) -> Dict[str, Processor]:
    return {
        TARGET_SUMMARIZER: SummarizerProcessor(workout_repo),
        TARGET_ROUTER: RouterProcessor(workout_repo, diet_repo),
        TARGET_DIET: DietProcessor(diet_repo),
    }
