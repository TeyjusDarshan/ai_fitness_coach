"""Tests for backend/coach_agent/context.py against fake repositories."""
from datetime import datetime, timezone

import pytest

from backend.coach_agent.context import SummaryNeededError, build_context, parse_reps

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)


def _exercise(eid, name, low, high, timed=False, joints=(), avoid_if=""):
    return {
        "id": eid, "name": name, "min_reps": low, "max_reps": high, "is_time_based": timed, "avoid_if": avoid_if,
        "movement_types": {"name": "squat"},
        "exercise_loaded_joints": [{"joint_load": load, "joints": {"name": joint}} for joint, load in joints],
    }


SESSION = {
    "id": 88, "day_number": 1, "scheduled_date": "2026-11-30", "kind": "strength",
    "plans": {"user_id": "usr_1", "plan_type": "3_day", "parent_plan_id": 40, "coach_notes": "Go slow",
              "safety_summary": {"excluded_joints": [], "excluded_movements": ["jumping"]}},
    "session_exercises": [
        {"id": 2, "exercise_id": 11, "category": "secondary", "slot_label": "Pull", "sets": 2, "reps": "12",
         "note": None, "skipped": True, "exercises": _exercise(11, "Row", 8, 15),
         "session_exercise_set_logs": []},
        {"id": 1, "exercise_id": 10, "category": "primary", "slot_label": "Squat", "sets": 3, "reps": "12,10,10",
         "note": "Slow", "skipped": False,
         "exercises": _exercise(10, "Squat", 6, 12, joints=[("knee", "high"), ("ankle", "nil")], avoid_if="knee surgery"),
         "session_exercise_set_logs": []},
    ],
}


class FakeCoachRepo:
    def __init__(self):
        self.history_args = None

    def get_exercise_edges(self, ids):
        assert sorted(ids) == [10, 11]
        return [
            {"from_exercise_id": 10, "type": "progression", "reason": "RIR > 3",
             "exercises": _exercise(20, "Split squat", 5, 10)},
            {"from_exercise_id": 10, "type": "regression", "reason": "Lack of strength",
             "exercises": _exercise(30, "Sit to stand", 8, 15)},
        ]

    def get_same_day_history(self, parent_plan_id, day_number):
        self.history_args = (parent_plan_id, day_number)
        return [
            {"id": 79, "completed_at": "2026-11-23T02:00:00+00:00", "scheduled_date": "2026-11-23", "is_period": True,
             "session_exercises": [{"id": 70, "sets": 3, "reps": "11", "skipped": False,
                                    "exercises": {"name": "Squat", "is_time_based": False},
                                    "session_exercise_set_logs": [{"set_number": 2, "completed_reps": 10},
                                                                  {"set_number": 1, "completed_reps": 11}],
                                    "session_exercise_rpe": {"rpe": 10}}]},
            {"id": 75, "completed_at": None, "scheduled_date": "2026-11-16", "is_period": False,
             "session_exercises": []},
        ]


class FakeSummaryRepo:
    def __init__(self, covers_until="2026-11-24T00:00:00+00:00", latest=True):
        self.latest = {"version": 3, "storage_path": "usr_1/v3.txt", "covers_until": covers_until} if latest else None
        self.period_args = None

    def get_latest(self, user_id):
        return self.latest

    def read_text(self, path):
        assert path == "usr_1/v3.txt"
        return "PAIN AND INJURIES\n- Knee: mild, comes and goes (2026-11-19)\n"

    def get_joint_pain(self, user_id):
        return [{"joint": "knee", "pain_level": "mild", "updated_at": "2026-11-19T00:00:00+00:00"}]

    def get_plans(self, user_id):
        return [{"id": 40, "completed_at": "2026-11-29T00:00:00+00:00"}, {"id": 41, "completed_at": None}]

    def get_question_rounds(self, user_id):
        return [{
            "session_id": 80, "round": 1, "status": "answered", "asked_at": "2026-11-25T02:00:00+00:00",
            "sessions": {"completed_at": "2026-11-25T01:00:00+00:00", "kind": "strength"},
            "questions": [{"id": "q1", "text": "தமிழ்", "intent": "How easy was the squat", "session_exercise_id": 81}],
            "answers": {"q1": {"summary": "Could do 5 more reps.", "reply_id": 9}},
            "clarification_replies": [{"id": 9, "created_at": "2026-11-25T05:00:00+00:00"}],
        }]

    def get_exercise_names(self, ids):
        return {81: "Squat"}

    def get_period_logs(self, user_id, since, until):
        self.period_args = (since, until)
        return [{"logged_on": "2026-11-23"}]


class FakePlanRepo:
    def get_user_workout_history(self, user_id):
        return {"scheduled": [], "past": [
            {"session_id": 80, "plan_id": 41, "day_number": 3, "kind": "strength", "name": "Full Body",
             "scheduled_date": "2026-11-25", "date": "2026-11-25", "status": "completed",
             "completed_at": "2026-11-25T01:00:00+00:00", "duration_seconds": 1800, "is_period": False,
             "exercises": [{"name": "Squat", "is_time_based": False, "sets": 3, "reps": "10",
                            "set_logs": [{"set_number": n, "completed_reps": 10} for n in (1, 2, 3)],
                            "rpe": 6, "rpe_logged": True, "skipped": False}]},
            # Older than 7 days: left to the summary.
            {"session_id": 60, "plan_id": 40, "day_number": 1, "kind": "strength", "name": "Full Body",
             "scheduled_date": "2026-11-10", "date": "2026-11-10", "status": "completed",
             "completed_at": "2026-11-10T01:00:00+00:00", "exercises": []},
        ]}


def _build(summary_repo=None):
    coach, summary = FakeCoachRepo(), summary_repo or FakeSummaryRepo()
    text, facts = build_context(coach, summary, FakePlanRepo(), SESSION, now=NOW)
    return coach, summary, text, facts


def test_build_context_renders_every_section_as_plain_text():
    coach, summary, text, facts = _build()
    assert coach.history_args == (40, 1)
    assert summary.period_args == (datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc), NOW)
    assert not text.lstrip().startswith("{")

    workout = facts["sections"]["workout"]
    assert "Coach notes this week: Go slow" in workout
    assert "Plan safety limits: excluded movements: jumping" in workout
    assert "Joint pain on file now: knee mild" in workout
    squat = next(line for line in workout.splitlines() if line.startswith("[session_exercise_id 1]"))
    assert squat == ("[session_exercise_id 1] Squat · open · reps, allowed 6-12 per set · prescribed 3 sets: "
                     "12, 10, 10 reps · loads knee high · avoid if: knee surgery · coach note: Slow")
    assert "  progression: [exercise_id 20] Split squat · reps, allowed 5-10 per set · when: RIR > 3" in workout
    assert "  regression: [exercise_id 30] Sit to stand" in workout
    assert "[session_exercise_id 2] Row · skipped (no suggestion)" in workout
    assert "Split squat" not in workout.split("[session_exercise_id 2]")[1]  # no options for a skipped one

    assert facts["sections"]["summary"].startswith("PAIN AND INJURIES")
    recent = facts["sections"]["last_7_days"]
    assert "- Squat: planned 3 x 10 reps; done 10, 10, 10; felt too easy" in recent
    assert "How easy was the squat -> Answer: Could do 5 more reps." in recent
    assert "தமிழ்" not in text
    assert "2026-11-10" not in recent
    assert "Period days logged: 2026-11-23" in recent

    same_day = facts["sections"]["same_day_history"]
    assert "1 week before: 2026-11-23 · completed · on her period" in same_day
    assert "- Squat: planned 3 x 11 reps; done 11, 10 (1 set(s) not done); felt too hard" in same_day
    assert "2 weeks before: 2026-11-16 · missed" in same_day

    for name in ("workout", "summary", "last_7_days", "same_day_history"):
        assert f"===== [{name}]" in text


def test_facts_for_validation():
    _, _, _, facts = _build()
    assert facts["user_id"] == "usr_1" and facts["summary_version"] == 3
    assert facts["exercises"][1]["actionable"] and not facts["exercises"][2]["actionable"]
    assert facts["exercises"][1]["reps"] == [12, 10, 10]
    assert set(facts["exercises"][1]["options"]["progression"]) == {20}


@pytest.mark.parametrize("summary_repo, says", [
    (FakeSummaryRepo(latest=False), "no summary yet"),
    (FakeSummaryRepo(covers_until="2026-11-18T00:00:00+00:00"), "only goes up to 2026-11-18"),
])
def test_a_missing_or_old_summary_asks_for_one(summary_repo, says):
    with pytest.raises(SummaryNeededError) as raised:
        build_context(FakeCoachRepo(), summary_repo, FakePlanRepo(), SESSION, now=NOW)
    assert says in raised.value.message


def test_parse_reps():
    assert parse_reps("12", 3) == [12, 12, 12]
    assert parse_reps("12,10,10", 3) == [12, 10, 10]
    assert parse_reps(None, 3) == []
