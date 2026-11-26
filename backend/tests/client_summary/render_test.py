"""Tests for backend/client_summary/render.py (pure)."""
from datetime import datetime, timezone

from backend.client_summary import render

TZ = "Asia/Kolkata"
UNTIL = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
SINCE = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


def test_parse_ts_handles_short_fractions_offsets_and_space():
    assert render.parse_ts("2026-11-26 04:10:30.24048+00").isoformat() == "2026-11-26T04:10:30.240480+00:00"
    assert render.parse_ts("2026-11-26T05:39:21.7+05:30").utcoffset().total_seconds() == 19800
    assert render.parse_ts("2026-11-26T05:39:21Z").tzinfo is not None
    assert render.parse_ts(None) is None


def test_in_window_is_after_since_up_to_until():
    assert render.in_window(UNTIL, SINCE, UNTIL)
    assert not render.in_window(SINCE, SINCE, UNTIL)
    assert render.in_window(SINCE, None, UNTIL)
    assert not render.in_window(None, None, UNTIL)


def test_profile_lines_flatten_and_leave_out_unset_values():
    lines = render.profile_lines({
        "user_id": "u1",
        "health": {"conditions": [{"name": "osteoarthritis", "location": "knee", "severity": None}],
                   "past_injuries": [], "medical_clearance_obtained": False},
        "goals": {"primary_goal": "strength", "target_timeline_weeks": None},
    })
    assert lines == [
        "health.conditions: name osteoarthritis, location knee",
        "health.medical clearance obtained: no",
        "goals.primary goal: strength",
    ]


def test_state_hash_ignores_when_pain_was_touched_but_not_its_level():
    row = {"name": "A", "gender": "female", "profile": {"goals": {"primary_goal": "strength"}}}
    a = render.state_hash(row, [{"joint": "knee", "pain_level": "mild", "updated_at": "2026-11-01T00:00:00+00:00"}])
    b = render.state_hash(row, [{"joint": "knee", "pain_level": "mild", "updated_at": "2026-11-20T00:00:00+00:00"}])
    c = render.state_hash(row, [{"joint": "knee", "pain_level": "moderate"}])
    assert a == b != c


def _exercise(**overrides):
    ex = {"name": "Squat", "is_time_based": False, "sets": 3, "reps": "10",
          "set_logs": [{"set_number": 1, "completed_reps": 10}, {"set_number": 2, "completed_reps": 9}],
          "rpe": 10, "rpe_logged": True, "skipped": False}
    ex.update(overrides)
    return ex


def test_exercise_line_planned_done_missing_and_effort():
    assert render.exercise_line(_exercise()) == (
        "- Squat: planned 3 x 10 reps; done 10, 9 (1 set(s) not done); felt too hard"
    )


def test_exercise_line_never_writes_unrated_as_a_rating():
    line = render.exercise_line(_exercise(rpe=8, rpe_logged=False))
    assert "effort not rated" in line and "about right" not in line


def test_exercise_line_timed_per_set_and_coach_skip():
    assert render.exercise_line(_exercise(is_time_based=True, reps="35,30", sets=2, set_logs=[], rpe_logged=False)) == (
        "- Squat: planned 35, 30 s; no sets done"
    )
    assert render.exercise_line(_exercise(skipped=True, skip_reason="knee")) == (
        "- Squat: skipped by the coach for this workout (knee)"
    )


def test_cardio_line_lists_skips_early_stops_and_period_shortening():
    line = render.cardio_line({
        "rounds": 1, "work_seconds": 21, "planned_work_seconds": 30, "rating": None,
        "log": [
            {"name": "Side step", "planned_seconds": 21, "actual_seconds": 21, "skipped": False},
            {"name": "Punches", "planned_seconds": 21, "actual_seconds": 5, "skipped": True},
            {"name": "Taps", "planned_seconds": 21, "actual_seconds": 10, "skipped": False},
        ],
        "log_summary": {"exercises_done": 2, "exercises_missing": 1, "rests_skipped": 0},
    })
    assert "level 30 s, shortened for her period" in line
    assert "not rated" in line
    assert "skipped Punches (5 s in)" in line
    assert "stopped early: Taps (10 of 21 s)" in line
    assert "1 exercise(s) never reached" in line


def _workout(**overrides):
    w = {"session_id": 1, "plan_id": 7, "day_number": 1, "kind": "strength", "name": "Full Body",
         "scheduled_date": "2026-11-25", "date": "2026-11-25", "status": "completed",
         "completed_at": "2026-11-25T03:00:00+00:00", "started_at": "2026-11-25T02:00:00+00:00",
         "duration_seconds": 3000, "is_period": False, "exercises": [_exercise()]}
    w.update(overrides)
    return w


def test_workout_lines_window_order_counts_and_missed():
    plans = {7: {"id": 7, "completed_at": None}}
    old = _workout(session_id=0, date="2026-11-20", scheduled_date="2026-11-20", completed_at="2026-11-20T03:00:00+00:00")
    # Scheduled 2026-11-24, never done: missed from 2026-11-25 00:00 IST (inside the window).
    missed = _workout(session_id=2, status="missed", completed_at=None, started_at=None, date="2026-11-24",
                      scheduled_date="2026-11-24", exercises=[_exercise(set_logs=[])])
    lines = render.workout_lines([_workout(), old, missed], plans, {7: 3}, SINCE, UNTIL, TZ)
    assert lines[0] == "Counts (2026-11-24 to 2026-11-25): 2 workouts; strength 1 completed, 1 missed; cardio 0 completed, 0 missed"
    assert lines[1] == "2026-11-24 (Tue) · Week 3, Day 1 · Full Body · missed"
    assert lines[2] == "2026-11-25 (Wed) · Week 3, Day 1 · Full Body · completed in 50 min"
    assert not any("2026-11-20" in line for line in lines)


def test_missed_time_uses_an_earlier_plan_close():
    w = _workout(status="missed", completed_at=None, scheduled_date="2026-12-10")
    closed = {"completed_at": "2026-11-25T00:00:00+00:00"}
    assert render.workout_event_time(w, closed, TZ) == render.parse_ts(closed["completed_at"])


def _round(**overrides):
    row = {
        "session_id": 5, "round": 1, "status": "answered", "asked_at": "2026-11-25T02:00:00+00:00",
        "sessions": {"completed_at": "2026-11-25T01:00:00+00:00", "kind": "strength"},
        "questions": [
            {"id": "q1", "text": "தமிழ் கேள்வி", "intent": "Check her knee", "joint": "knee", "session_exercise_id": 40},
            {"id": "q2", "text": "இன்னொன்று", "intent": "Any discomfort", "joint": None, "session_exercise_id": None},
        ],
        "answers": {"q1": {"summary": "Knee fine.", "reply_id": 9}},
        "clarification_replies": [{"id": 9, "created_at": "2026-11-25T05:00:00+00:00"}],
    }
    row.update(overrides)
    return row


def test_qa_lines_english_only_and_unanswered_marked():
    lines = render.qa_lines([_round()], {40: "Squat"}, SINCE, UNTIL, TZ)
    assert lines == [
        "After the 2026-11-25 strength workout:",
        "- About Squat / knee: Check her knee -> Answer: Knee fine.",
        "- Any discomfort -> Not answered.",
    ]
    assert not any("தமிழ்" in line for line in lines)


def test_qa_lines_late_answer_to_an_earlier_question():
    row = _round(asked_at="2026-11-23T02:00:00+00:00",
                 sessions={"completed_at": "2026-11-23T01:00:00+00:00", "kind": "cardio"})
    lines = render.qa_lines([row], {40: "Squat"}, SINCE, UNTIL, TZ)
    assert lines == [
        "- Answer received 2026-11-25 to a question asked after the 2026-11-23 workout. "
        "About Squat / knee: Check her knee -> Answer: Knee fine."
    ]


def test_qa_lines_answer_after_the_cutoff_waits_for_the_next_run():
    row = _round(status="open", clarification_replies=[{"id": 9, "created_at": "2026-11-27T00:00:00+00:00"}])
    lines = render.qa_lines([row], {40: "Squat"}, SINCE, UNTIL, TZ)
    assert "- About Squat / knee: Check her knee -> No answer yet." in lines


def test_comment_lines_use_the_english_comment_never_the_quote():
    lines = render.comment_lines([{
        "comment": "Knee ached after walking.", "quote": "முட்டி வலி", "source": "clarification_reply",
        "urgent": True, "created_at": "2026-11-25T05:00:00+00:00", "exercises": {"name": "Squat"},
    }, {"comment": None, "quote": "x", "created_at": "2026-11-25T06:00:00+00:00"}], TZ)
    assert lines == ["- 2026-11-25 · Squat · WhatsApp reply: Knee ached after walking. [URGENT]"]


def test_render_input_update_and_empty_sections():
    text = render.render_input(
        today=UNTIL.date(), state="CLIENT (current profile)", previous_summary="OLD", since=SINCE, until=UNTIL,
        timezone=TZ, workouts=[], qa=["q"], comments=[], period=[],
    )
    assert "UPDATE: the previous summary covers everything up to 2026-11-24 17:30." in text
    assert "PREVIOUS SUMMARY\nOLD" in text
    assert "WORKOUTS (oldest first)\nnone" in text
    assert "QUESTIONS WE ASKED AND HER ANSWERS\nq" in text
