"""Tests for backend/coach_agent/validate.py — every check the AI Coach's
suggestions go through before the coach sees them."""
import pytest

from backend.coach_agent.agent import Evidence, ExerciseSuggestion
from backend.coach_agent.validate import quote_found, stored_reps, validate_suggestions


def _facts(**overrides):
    squat = {
        "session_exercise_id": 1, "exercise_id": 10, "name": "Squat", "is_time_based": False,
        "sets": 3, "reps": [10, 10, 10], "reps_stored": "10", "min": 6, "max": 12, "actionable": True,
        "options": {
            "progression": {20: {"exercise_id": 20, "name": "Split squat", "min": 5, "max": 10}},
            "regression": {30: {"exercise_id": 30, "name": "Sit to stand", "min": 8, "max": 15}},
        },
    }
    row = {
        "session_exercise_id": 2, "exercise_id": 11, "name": "Row", "is_time_based": False,
        "sets": 2, "reps": [12, 12], "reps_stored": "12", "min": 8, "max": 15, "actionable": True,
        "options": {"progression": {}, "regression": {}},
    }
    facts = {
        "user_id": "usr_1",
        "exercises": {1: squat, 2: row},
        "client_texts": ["Knee hurt a little on the way down.", "முட்டி கொஞ்சம் வலிக்குது"],
    }
    facts.update(overrides)
    return facts


DATA = [Evidence(source="set_logs", quote="Nov 9: 10, 10, 10", session_id=79)]


def _s(seid=1, action="adjust", sets=None, reps=None, to=None, reason="Because.", evidence=DATA):
    return ExerciseSuggestion(
        session_exercise_id=seid, action=action, sets=sets, reps=reps, to_exercise_id=to,
        reason=reason, evidence=evidence,
    )


def _one(suggestion, facts=None):
    rows = validate_suggestions([suggestion, _s(seid=2, action="keep")], facts or _facts())
    return next(row for row in rows if row["session_exercise_id"] == suggestion.session_exercise_id)


def test_a_valid_adjust_is_pending_with_stored_reps():
    row = _one(_s(sets=3, reps=[12, 11, 11]))
    assert (row["action"], row["status"], row["proposed_sets"], row["proposed_reps"]) == ("adjust", "pending", 3, "12,11,11")
    assert row["before"] == {"exercise_id": 10, "name": "Squat", "sets": 3, "reps": "10"}


def test_a_single_target_is_spread_over_the_sets():
    assert _one(_s(sets=3, reps=[11]))["proposed_reps"] == "11"


@pytest.mark.parametrize("sets, reps, why", [
    (3, [13, 10, 10], "within 6-12"),
    (3, [10, 10], "one target per set"),
    (7, [10] * 7, "sets must be 1-6"),
])
def test_an_invalid_adjust_falls_back_to_keep(sets, reps, why):
    row = _one(_s(sets=sets, reps=reps))
    assert (row["action"], row["status"]) == ("keep", "no_change")
    assert why in row["reason"]


def test_an_adjust_that_changes_nothing_is_a_keep():
    row = _one(_s(sets=3, reps=[10, 10, 10]))
    assert (row["action"], row["status"]) == ("keep", "no_change")


def test_progress_only_to_a_listed_option_and_defaults_to_its_min():
    row = _one(_s(action="progress", to=20))
    assert (row["status"], row["proposed_exercise_id"], row["proposed_sets"], row["proposed_reps"]) == ("pending", 20, 3, "5")

    row = _one(_s(action="progress", to=30))  # a regression target, not a progression
    assert row["status"] == "no_change"
    assert "progression options" in row["reason"]


def test_regress_defaults_to_the_targets_max_and_checks_its_range():
    assert _one(_s(action="regress", to=30))["proposed_reps"] == "15"
    assert _one(_s(action="regress", to=30, reps=[16, 16, 16]))["status"] == "no_change"


def test_skip_is_pending_and_needs_no_numbers():
    row = _one(_s(action="skip"))
    assert (row["action"], row["status"], row["proposed_sets"]) == ("skip", "pending", None)


def test_a_fabricated_client_quote_is_dropped_and_a_real_one_kept():
    evidence = [
        Evidence(source="client_answer", quote="My knee is totally fine", session_id=79),
        Evidence(source="client_comment", quote="knee hurt a little", session_id=79),
        Evidence(source="client_comment", quote="முட்டி கொஞ்சம் வலிக்குது", session_id=80),
    ]
    row = _one(_s(action="skip", evidence=evidence))
    assert [(e["quote"], e["verified"]) for e in row["evidence"]] == [
        ("knee hurt a little", True), ("முட்டி கொஞ்சம் வலிக்குது", True),
    ]


def test_a_change_with_only_fabricated_evidence_is_not_suggested():
    evidence = [Evidence(source="client_answer", quote="never said this", session_id=1)]
    row = _one(_s(action="skip", evidence=evidence))
    assert row["status"] == "no_change"
    assert "no verifiable evidence" in row["reason"]


def test_a_change_needs_a_reason():
    assert _one(_s(action="skip", reason="  "))["status"] == "no_change"


def test_every_actionable_exercise_gets_a_row_and_foreign_ids_are_ignored():
    rows = validate_suggestions([_s(seid=99, action="skip"), _s(seid=1, action="skip")], _facts())
    assert [(r["session_exercise_id"], r["action"]) for r in rows] == [(1, "skip"), (2, "keep")]
    assert rows[1]["reason"] == "No suggestion from the AI coach for this exercise."


def test_locked_or_skipped_exercises_get_no_suggestion():
    facts = _facts()
    facts["exercises"][2]["actionable"] = False
    rows = validate_suggestions([_s(seid=2, action="skip")], facts)
    assert [r["session_exercise_id"] for r in rows] == [1]


def test_only_the_first_suggestion_per_exercise_counts():
    rows = validate_suggestions([_s(action="skip"), _s(sets=3, reps=[11])], _facts())
    assert rows[0]["action"] == "skip"


def test_helpers():
    assert stored_reps([10, 10]) == "10"
    assert stored_reps([12, 10]) == "12,10"
    assert quote_found("KNEE hurt, a little", ["Knee hurt a little on the way down."])
    assert not quote_found("", ["anything"])
