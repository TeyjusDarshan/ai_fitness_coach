"""Tests for transcribing the client's voice feedback into the analysis.

The _process_message tests mock everything outside the consumer (the
transcription, the Claude extraction and summary, the voice note, WhatsApp
and Kafka), so they only check the wiring. test_transcribe_feedback_against_real_sarvam
(bottom of file) downloads a real recording and calls Sarvam for real, same
convention as main_test.py.
"""
import os
from unittest.mock import MagicMock

import pytest

from workout_analysis_consumer import main
from workout_analysis_consumer.feedback_agent import Question
from workout_analysis_consumer.summarizer import WorkoutSummary
from workout_analysis_consumer.feedback import transcribe_feedback
from workout_analysis_consumer.repository import AnalysisRepository

SESSION_ID = int(os.environ.get("ANALYSIS_IT_SESSION_ID", "0"))


def _summary(questions=()):
    return WorkoutSummary(
        summary="analysis text",
        questions_intro="Oru sila kelvigal:",
        questions=[
            Question(text=text, intent="why", topic="too_hard", session_exercise_id=seid, joint=None)
            for text, seid in questions
        ],
        closing="Bye!",
    )


@pytest.fixture
def mocks(monkeypatch):
    mocks = {
        "transcribe_many": MagicMock(side_effect=lambda paths: {
            key: f"transcript of {path}" for key, path in paths.items()
        }),
        "extract_feedback": MagicMock(return_value=[]),
        "generate_workout_summary": MagicMock(return_value=_summary()),
        "generate_voice_note": MagicMock(return_value=None),
        "producer": MagicMock(),
        "whatsapp_client": MagicMock(),
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(main, name, mock)
    return mocks


def _repo(feedback_audio_path, exercise_paths=None):
    repo = MagicMock()
    repo.fetch_context.return_value = {
        "session_id": 48, "plan_id": 7, "day_number": 1, "user_id": "usr_1",
        "feedback_audio_path": feedback_audio_path,
        "exercise_feedback_audio_paths": exercise_paths or {},
        "exercises": [
            {"session_exercise_id": 301, "exercise_id": 12, "name": "Squat"},
            {"session_exercise_id": 302, "exercise_id": 14, "name": "Row"},
        ],
    }
    repo.list_joints.return_value = {"knee": 2, "spine": 4}
    repo.fetch_question_history.return_value = []
    return repo


def _summary_context(mocks):
    mocks["generate_workout_summary"].assert_called_once()
    return mocks["generate_workout_summary"].call_args.args[0]


def test_voice_feedback_transcript_is_sent_to_claude_without_the_storage_path(mocks):
    main._process_message(_repo("session_48.webm"), 48, "919876543210")

    mocks["transcribe_many"].assert_called_once_with({"session": "session_48.webm"})
    context = _summary_context(mocks)
    assert context["client_voice_feedback"] == "transcript of session_48.webm"
    assert "feedback_audio_path" not in context
    assert "exercise_feedback_audio_paths" not in context


def test_exercise_voice_notes_are_transcribed_and_extracted(mocks):
    rows = [{
        "session_exercise_id": 301, "exercise_id": 12, "category": "joint_pain",
        "difficulty": None, "joint_id": 2, "pain_level": "moderate", "urgent": False,
        "comment": "Knee hurt in squats.", "quote": "knee", "source": "exercise_voice_note",
    }]
    mocks["extract_feedback"].return_value = rows
    repo = _repo(None, {301: "session_48_exercise_301.webm"})

    main._process_message(repo, 48, "919876543210")

    [voice_note] = mocks["extract_feedback"].call_args.args[0]
    assert (voice_note.id, voice_note.source, voice_note.session_exercise_id) == (
        "exercise_301", "exercise_voice_note", 301
    )
    repo.replace_voice_note_comments.assert_called_once_with("usr_1", 48, rows)
    repo.apply_joint_pain.assert_called_once_with("usr_1", {2: "moderate"})
    context = _summary_context(mocks)
    assert context["exercises"][0]["client_voice_note"] == "transcript of session_48_exercise_301.webm"
    assert context["client_feedback_notes"] == [
        {"session_exercise_id": 301, "category": "joint_pain", "comment": "Knee hurt in squats."}
    ]


def test_earlier_questions_and_answers_are_given_to_the_summary(mocks):
    history = [{"session_id": 40, "questions": [{"question": "Knee eppadi?", "answer": "Hurts a bit."}]}]
    repo = _repo(None)
    repo.fetch_question_history.return_value = history

    main._process_message(repo, 48, "919876543210")

    repo.fetch_question_history.assert_called_once_with("usr_1", 48)
    assert _summary_context(mocks)["previous_questions_and_answers"] == history


def test_no_or_failed_history_leaves_it_out(mocks):
    repo = _repo(None)
    repo.fetch_question_history.side_effect = RuntimeError("db down")

    main._process_message(repo, 48, "919876543210")

    assert "previous_questions_and_answers" not in _summary_context(mocks)


def test_a_failed_extraction_still_generates_the_analysis(mocks):
    mocks["extract_feedback"].side_effect = RuntimeError("claude down")
    repo = _repo("session_48.webm")

    main._process_message(repo, 48, "919876543210")

    repo.replace_voice_note_comments.assert_not_called()
    repo.save_analysis.assert_called_once_with(48, "analysis text Bye!", None)


def test_no_transcripts_skips_extraction(mocks):
    mocks["transcribe_many"].side_effect = lambda paths: {}

    main._process_message(_repo("session_48.webm"), 48, "919876543210")

    assert "client_voice_feedback" not in _summary_context(mocks)
    mocks["extract_feedback"].assert_not_called()


def test_no_recording_skips_transcription(mocks):
    main._process_message(_repo(None), 48, "919876543210")

    mocks["transcribe_many"].assert_not_called()
    context = _summary_context(mocks)
    assert "client_voice_feedback" not in context
    assert "feedback_audio_path" not in context


def test_questions_are_spoken_and_saved_before_the_voice_note_is_sent(mocks):
    mocks["generate_workout_summary"].return_value = _summary(
        [("Squat yen kashtam?", 301), ("Vera edhavadhu?", 999)]
    )
    mocks["generate_voice_note"].return_value = "https://audio/day_1.ogg"
    repo = _repo(None)
    order = []
    repo.save_clarification.side_effect = lambda *a: order.append("saved")
    mocks["whatsapp_client"].send_audio.side_effect = lambda *a: order.append("sent")

    main._process_message(repo, 48, "919876543210")

    spoken = "analysis text Oru sila kelvigal: Squat yen kashtam? Vera edhavadhu? Bye!"
    mocks["generate_voice_note"].assert_called_once_with(spoken, 7, 1)
    repo.save_analysis.assert_called_once_with(48, spoken, "https://audio/day_1.ogg")
    repo.supersede_open_clarifications.assert_called_once_with("919876543210", 48)
    session_id, user_id, phone, round_number, questions = repo.save_clarification.call_args.args
    assert (session_id, user_id, phone, round_number) == (48, "usr_1", "919876543210", 1)
    assert [(q["id"], q["session_exercise_id"]) for q in questions] == [("q1", 301), ("q2", None)]
    assert order == ["saved", "sent"]
    mocks["whatsapp_client"].send_text.assert_not_called()


def test_questions_fall_back_to_text_when_there_is_no_voice_note(mocks):
    mocks["generate_workout_summary"].return_value = _summary([("Squat yen kashtam?", 301)])
    mocks["generate_voice_note"].side_effect = RuntimeError("tts down")

    main._process_message(_repo(None), 48, "919876543210")

    mocks["whatsapp_client"].send_text.assert_called_once_with(
        "919876543210", "Oru sila kelvigal:\n\n1. Squat yen kashtam?\n\nBye!"
    )


@pytest.mark.integration
@pytest.mark.skipif(not SESSION_ID, reason="set ANALYSIS_IT_SESSION_ID to a test sessions row")
def test_transcribe_feedback_against_real_sarvam():
    """No mocking: downloads the ANALYSIS_IT_SESSION_ID session's recording
    from the voice-feedback bucket and runs a real Sarvam batch job on it."""
    context = AnalysisRepository().fetch_context(SESSION_ID)
    assert context is not None
    if not context["feedback_audio_path"]:
        pytest.skip("this session has no recorded voice feedback")

    transcript = transcribe_feedback(context["feedback_audio_path"])

    assert transcript.strip()
