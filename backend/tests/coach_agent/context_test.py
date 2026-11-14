"""Tests for backend/coach_agent/context.py against a fake repository."""
from backend.coach_agent.context import build_context, parse_reps


def _exercise(eid, name, low, high, timed=False, joints=()):
    return {
        "id": eid, "name": name, "min_reps": low, "max_reps": high, "is_time_based": timed, "avoid_if": "",
        "movement_types": {"name": "squat"},
        "exercise_loaded_joints": [{"joint_load": load, "joints": {"name": joint}} for joint, load in joints],
    }


SESSION = {
    "id": 88, "day_number": 1, "scheduled_date": "2026-11-16", "kind": "strength",
    "plans": {"user_id": "usr_1", "plan_type": "3_day", "parent_plan_id": 40, "coach_notes": "Go slow",
              "safety_summary": {"excluded_joints": []}},
    "session_exercises": [
        {"id": 2, "exercise_id": 11, "category": "secondary", "slot_label": "Pull", "sets": 2, "reps": "12",
         "note": None, "skipped": True, "exercises": _exercise(11, "Row", 8, 15),
         "session_exercise_set_logs": []},
        {"id": 1, "exercise_id": 10, "category": "primary", "slot_label": "Squat", "sets": 3, "reps": "12,10,10",
         "note": "Slow", "skipped": False, "exercises": _exercise(10, "Squat", 6, 12, joints=[("knee", "high")]),
         "session_exercise_set_logs": []},
    ],
}


class FakeRepo:
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

    def get_client(self, user_id):
        return {
            "profile_row": {"name": "Asha", "gender": "female", "profile": {"health": {"conditions": ["knee OA"]}}},
            "joint_pain": [{"joint": "knee", "pain_level": "mild", "updated_at": "2026-11-10"}],
            "period_days": [],
        }

    def get_same_day_history(self, parent_plan_id, day_number):
        self.history_args = (parent_plan_id, day_number)
        return [
            {"id": 79, "completed_at": "2026-11-09T02:00:00+00:00", "scheduled_date": "2026-11-09", "is_period": False,
             "session_exercises": [{"id": 70, "sets": 3, "reps": "11", "skipped": False,
                                    "exercises": {"name": "Squat", "is_time_based": False},
                                    "session_exercise_set_logs": [{"set_number": 2, "completed_reps": 10},
                                                                  {"set_number": 1, "completed_reps": 11}],
                                    "session_exercise_rpe": {"rpe": 10}}]},
            {"id": 75, "completed_at": None, "scheduled_date": "2026-11-02", "is_period": False,
             "session_exercises": []},
        ]

    def get_question_history(self, user_id, session_id):
        return [{"session_id": 79, "questions": [{"question": "Q?", "answer": "Knee hurt going down."}]}]

    def get_recent_comments(self, user_id):
        return [{"session_id": 79, "quote": "முட்டி வலிக்குது", "comment": "Knee pain in squats."}]


def test_build_context_shapes_exercises_history_and_facts():
    repo = FakeRepo()

    context, facts = build_context(repo, SESSION)

    assert repo.history_args == (40, 1)
    squat, row = context["exercises"]  # primary first
    assert (squat["name"], squat["prescribed_reps"], squat["min"], squat["max"], squat["status"]) == (
        "Squat", [12, 10, 10], 6, 12, "open"
    )
    assert squat["loaded_joints"] == [{"joint": "knee", "load": "high"}]
    assert [o["name"] for o in squat["progression_options"]] == ["Split squat"]
    assert squat["regression_options"][0]["edge_reason"] == "Lack of strength"
    assert row["status"] == "skipped"

    week = context["same_day_last_two_weeks"]
    assert (week[0]["status"], week[0]["exercises"][0]["logged_reps_per_set"], week[0]["exercises"][0]["felt"]) == (
        "completed", [11, 10], "too hard"
    )
    assert week[1]["status"] == "missed"
    assert context["client"]["name"] == "Asha"
    assert context["session"]["split_name"]

    assert facts["user_id"] == "usr_1"
    assert facts["exercises"][1]["actionable"] and not facts["exercises"][2]["actionable"]
    assert set(facts["exercises"][1]["options"]["progression"]) == {20}
    assert "Knee hurt going down." in facts["client_texts"]
    assert "முட்டி வலிக்குது" in facts["client_texts"]


def test_parse_reps():
    assert parse_reps("12", 3) == [12, 12, 12]
    assert parse_reps("12,10,10", 3) == [12, 10, 10]
    assert parse_reps(None, 3) == []
