"""Tests for the voice-feedback agent's validation and Claude calls.

The Anthropic client is mocked (module-level `client`, as in
summarizer_test.py), so nothing here calls a real service.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from workout_analysis_consumer import feedback_agent
from workout_analysis_consumer.feedback_agent import (
    AnswerSummary,
    ExtractedNote,
    FeedbackExtraction,
    FeedbackRefusedError,
    Question,
    ReplyMapping,
    ReplyNote,
    VoiceNote,
    extract_feedback,
    joint_pain_changes,
    map_reply,
    quote_in_text,
    validate_note,
    validate_questions,
)

JOINTS = {"knee": 2, "spine": 4, "shoulder": 5}
CONTEXT = {
    "session_id": 48,
    "exercises": [
        {"session_exercise_id": 301, "exercise_id": 12, "name": "Squat"},
        {"session_exercise_id": 302, "exercise_id": 14, "name": "Row"},
    ],
    "joint_pain": [],
}
EXERCISE_IDS = {301: 12, 302: 14}


def _note(**overrides):
    fields = {
        "transcript_id": "session",
        "session_exercise_id": None,
        "category": "other",
        "difficulty": None,
        "joint": None,
        "pain_level": None,
        "urgent": False,
        "comment": "Said something.",
        "quote": "konjam valikkudhu",
    }
    fields.update(overrides)
    return ExtractedNote(**fields)


def _reply_note(**overrides):
    fields = _note(**overrides).model_dump()
    fields.pop("transcript_id")
    fields.setdefault("question_id", None)
    fields.update({k: v for k, v in overrides.items() if k == "question_id"})
    return ReplyNote(**fields)


def _question(text="Knee eppadi irukku?", seid=None, joint=None):
    return Question(text=text, intent="pain detail", topic="joint_pain", session_exercise_id=seid, joint=joint)


def _mock_client(monkeypatch, parsed, stop_reason="end_turn", stop_details=None):
    mock = MagicMock()
    mock.beta.messages.parse.return_value = SimpleNamespace(
        parsed_output=parsed, stop_reason=stop_reason, stop_details=stop_details
    )
    monkeypatch.setattr(feedback_agent, "client", mock)
    return mock


# ---------- quote check ----------

@pytest.mark.parametrize("quote, text, expected", [
    ("knee konjam valikkudhu", "Squat pannum bodhu Knee  konjam valikkudhu!", True),
    ("முட்டி வலிக்குது", "இன்னைக்கு squat-ல முட்டி வலிக்குது.", True),
    ("shoulder hurts", "Squat pannum bodhu knee konjam valikkudhu", False),
    ("", "anything", False),
    ("...", "anything", False),
])
def test_quote_in_text(quote, text, expected):
    assert quote_in_text(quote, text) is expected


# ---------- validate_note ----------

def test_a_note_whose_quote_the_client_never_said_is_dropped():
    note = _note(quote="my shoulder is killing me")
    assert validate_note(note, "knee konjam valikkudhu", EXERCISE_IDS, JOINTS) is None


def test_joint_pain_note_maps_joint_and_exercise():
    note = _note(category="joint_pain", joint="knee", pain_level="moderate", session_exercise_id=301)

    row = validate_note(note, "squat la knee konjam valikkudhu", EXERCISE_IDS, JOINTS)

    assert row == {
        "session_exercise_id": 301, "exercise_id": 12, "category": "joint_pain", "difficulty": None,
        "joint_id": 2, "pain_level": "moderate", "urgent": False,
        "comment": "Said something.", "quote": "konjam valikkudhu",
    }


def test_joint_pain_without_a_level_defaults_to_mild():
    note = _note(category="joint_pain", joint="knee")
    assert validate_note(note, "knee konjam valikkudhu", EXERCISE_IDS, JOINTS)["pain_level"] == "mild"


def test_an_unknown_exercise_falls_back_to_the_voice_notes_exercise():
    note = _note(session_exercise_id=999)

    row = validate_note(note, "konjam valikkudhu", EXERCISE_IDS, JOINTS, default_session_exercise_id=302)

    assert (row["session_exercise_id"], row["exercise_id"]) == (302, 14)


def test_an_unknown_exercise_with_no_fallback_is_session_level():
    row = validate_note(_note(session_exercise_id=999), "konjam valikkudhu", EXERCISE_IDS, JOINTS)
    assert (row["session_exercise_id"], row["exercise_id"]) == (None, None)


def test_a_joint_missing_from_the_table_is_unlinked():
    note = _note(category="joint_pain", joint="ankle")

    row = validate_note(note, "konjam valikkudhu", EXERCISE_IDS, JOINTS)

    assert row["joint_id"] is None
    assert joint_pain_changes([row]) == {}


def test_pain_resolved_with_no_known_joint_becomes_a_plain_note():
    note = _note(category="pain_resolved", joint=None)
    assert validate_note(note, "konjam valikkudhu", EXERCISE_IDS, JOINTS)["category"] == "other"


def test_difficulty_is_only_kept_on_difficulty_notes():
    note = _note(category="fatigue", difficulty="too_hard")
    assert validate_note(note, "konjam valikkudhu", EXERCISE_IDS, JOINTS)["difficulty"] is None


# ---------- joint_pain_changes ----------

def _row(category, joint_id, pain_level=None):
    return {"category": category, "joint_id": joint_id, "pain_level": pain_level}


def test_the_worst_level_in_a_batch_wins():
    rows = [_row("joint_pain", 2, "severe"), _row("joint_pain", 2, "mild"), _row("joint_pain", 4, "moderate")]
    assert joint_pain_changes(rows) == {2: "severe", 4: "moderate"}


def test_resolved_pain_clears_the_joint():
    assert joint_pain_changes([_row("pain_resolved", 4)]) == {4: None}


def test_pain_in_the_same_batch_beats_resolved():
    assert joint_pain_changes([_row("pain_resolved", 2), _row("joint_pain", 2, "mild")]) == {2: "mild"}


def test_non_pain_notes_change_nothing():
    assert joint_pain_changes([_row("difficulty", None), _row("other", 2)]) == {}


# ---------- validate_questions ----------

def test_questions_get_ids_and_unknown_links_are_dropped():
    questions = [
        _question("Squat eppadi?", seid=301, joint="knee"),
        _question("  "),
        _question("Vera edhavadhu?", seid=999, joint="ankle"),
    ]

    validated = validate_questions(questions, EXERCISE_IDS, JOINTS, "q", 4)

    assert [(q["id"], q["text"], q["session_exercise_id"], q["joint"]) for q in validated] == [
        ("q1", "Squat eppadi?", 301, "knee"),
        ("q2", "Vera edhavadhu?", None, None),
    ]


def test_only_the_first_question_per_exercise_is_kept():
    questions = [
        _question("Split squat yen kashtam?", seid=301),
        _question("Split squat-la knee valichudha?", seid=301, joint="knee"),
        _question("Row eppadi?", seid=302),
        _question("Vera edhavadhu?"),
        _question("Innum edhavadhu?"),
    ]

    validated = validate_questions(questions, EXERCISE_IDS, JOINTS, "q", 10)

    assert [q["text"] for q in validated] == [
        "Split squat yen kashtam?", "Row eppadi?", "Vera edhavadhu?", "Innum edhavadhu?",
    ]
    assert [q["id"] for q in validated] == ["q1", "q2", "q3", "q4"]


def test_questions_are_capped():
    questions = [_question(f"Q{i}?") for i in range(6)]
    assert len(validate_questions(questions, EXERCISE_IDS, JOINTS, "q", 4)) == 4


# ---------- extract_feedback ----------

def test_extract_feedback_validates_each_note_against_its_own_transcript(monkeypatch):
    voice_notes = [
        VoiceNote("session", "session_voice_note", None, None, "Workout nalla irundhuchu"),
        VoiceNote("exercise_301", "exercise_voice_note", 301, "Squat", "knee konjam valikkudhu"),
    ]
    mock = _mock_client(monkeypatch, FeedbackExtraction(notes=[
        _note(transcript_id="exercise_301", category="joint_pain", joint="knee", quote="knee konjam valikkudhu"),
        # Real words, but from the other transcript: dropped.
        _note(transcript_id="session", quote="knee konjam valikkudhu"),
        _note(transcript_id="nope", quote="nalla irundhuchu"),
        _note(transcript_id="session", category="enjoyment", quote="nalla irundhuchu"),
    ]))

    rows = extract_feedback(voice_notes, CONTEXT, JOINTS)

    assert [(r["category"], r["session_exercise_id"], r["source"]) for r in rows] == [
        ("joint_pain", 301, "exercise_voice_note"),
        ("enjoyment", None, "session_voice_note"),
    ]
    kwargs = mock.beta.messages.parse.call_args.kwargs
    assert kwargs["output_format"] is FeedbackExtraction
    assert kwargs["fallbacks"] == "default"


def test_extract_feedback_with_no_voice_notes_skips_claude(monkeypatch):
    mock = _mock_client(monkeypatch, None)
    assert extract_feedback([], CONTEXT, JOINTS) == []
    mock.beta.messages.parse.assert_not_called()


def test_extract_feedback_raises_on_refusal(monkeypatch):
    _mock_client(monkeypatch, None, stop_reason="refusal", stop_details=SimpleNamespace(category="bio"))
    with pytest.raises(FeedbackRefusedError, match="bio"):
        extract_feedback([VoiceNote("session", "session_voice_note", None, None, "hi")], CONTEXT, JOINTS)


# ---------- map_reply ----------

QUESTIONS = [
    {"id": "q1", "text": "Squat yen kashtam?", "intent": "why hard", "session_exercise_id": 301, "joint": None},
    {"id": "q2", "text": "Vera edhavadhu?", "intent": "other discomfort", "session_exercise_id": None, "joint": None},
]


def test_map_reply_keeps_known_answers_and_links_notes_to_the_question(monkeypatch):
    _mock_client(monkeypatch, ReplyMapping(
        answers=[
            AnswerSummary(question_id="q1", summary="Knee hurt."),
            AnswerSummary(question_id="q9", summary="Invented."),
        ],
        notes=[
            _reply_note(question_id="q1", category="joint_pain", joint="knee", pain_level="severe",
                        quote="knee romba valichudhu"),
            _reply_note(question_id="q9", quote="vera onnum illa"),
            _reply_note(quote="not in the reply"),
        ],
        follow_ups=[_question("Knee-la enga valikkudhu?", seid=301, joint="knee")],
    ))

    result = map_reply(QUESTIONS, [], "knee romba valichudhu, vera onnum illa", CONTEXT, JOINTS, True)

    assert result["answers"] == {"q1": "Knee hurt."}
    assert [(n["question_id"], n["session_exercise_id"], n["joint_id"], n["pain_level"]) for n in result["notes"]] == [
        ("q1", 301, 2, "severe"),  # exercise taken from the question
        (None, None, None, None),
    ]
    assert [(q["id"], q["joint"]) for q in result["follow_ups"]] == [("f1", "knee")]


def test_map_reply_never_returns_follow_ups_when_not_allowed(monkeypatch):
    _mock_client(monkeypatch, ReplyMapping(answers=[], notes=[], follow_ups=[_question()]))

    result = map_reply(QUESTIONS, [], "seri", CONTEXT, JOINTS, False)

    assert result["follow_ups"] == []


def test_map_reply_caps_follow_ups(monkeypatch):
    _mock_client(monkeypatch, ReplyMapping(answers=[], notes=[], follow_ups=[_question(f"Q{i}?") for i in range(4)]))
    assert len(map_reply(QUESTIONS, [], "seri", CONTEXT, JOINTS, True)["follow_ups"]) == 2
