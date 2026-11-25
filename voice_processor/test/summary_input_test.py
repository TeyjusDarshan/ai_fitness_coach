"""Tests for the workout summary's plain-text input (voice_processor/summary_input.py)."""
from voice_processor.summary_input import history_threads, render_context


def _exercise(**overrides):
    exercise = {
        "session_exercise_id": 834, "exercise_id": 58, "name": "standing wall plank", "movement_type": "carry",
        "slot": "Carry", "unit": "seconds", "prescribed_sets": 2, "prescribed_reps": "20,20", "rep_range": "15-60",
        "set_logs": [{"set_number": 1, "completed_reps": 6}, {"set_number": 2, "completed_reps": 2}],
        "rpe": 8, "effort_flag": None, "compared_to_last_time": "less", "is_new": False,
    }
    exercise.update(overrides)
    return exercise


def _history():
    """Newest first, as repository._shape_question_history returns it."""
    return [
        {"session_id": 3, "date": "2026-11-24", "day_number": 2, "workout_type": "cardio", "questions": [
            {"question": "முட்டி எப்படி இருக்கு?", "intent": "Follow up on her knee during cardio.",
             "exercise": None, "joint": "knee", "answer": None, "follow_up": False},
            {"question": "வேற ஏதாவது?", "intent": "Check for any other discomfort.",
             "exercise": None, "joint": None, "answer": "No other problems.", "follow_up": False},
        ]},
        {"session_id": 2, "date": "2026-11-19", "day_number": 4, "workout_type": "cardio", "questions": [
            {"question": "முட்டி?", "intent": "Is the knee pain better or worse?",
             "exercise": None, "joint": "knee", "answer": "Comes and goes; leg feels stronger.", "follow_up": True},
            {"question": "வேற ஏதாவது?", "intent": "Check for any other discomfort.",
             "exercise": None, "joint": None, "answer": "Knee pain in one leg since yesterday.", "follow_up": False},
        ]},
        {"session_id": 1, "date": "2026-11-18", "day_number": 3, "workout_type": "strength", "questions": [
            {"question": "முட்டி?", "intent": "How bad was the knee pain after the workout?",
             "exercise": None, "joint": "knee", "answer": "Osteoarthritis; mild pain all day when walking.",
             "follow_up": False},
        ]},
    ]


def test_an_exercise_is_one_line_led_by_its_id():
    text = render_context({"exercises": [_exercise()]})
    assert ("- session_exercise_id 834: standing wall plank | movement carry | unit seconds | prescribed_sets 2 | "
            "prescribed_reps 20,20 | rep_range 15-60 | set_logs 6, 2 | is_new no | compared_to_last_time less") in text


def test_unset_values_are_left_out_not_written_as_a_dash():
    # A "-" for effort_flag was read as a rating in testing.
    text = render_context({"exercises": [_exercise()], "user_profile": {"progress_tracking": {}, "goals": None}})
    assert "effort_flag" not in text
    assert " - " not in text.replace("\n- ", "\n")
    assert "progress_tracking" not in text and "goals" not in text


def test_a_rating_is_kept_and_unused_ids_are_dropped():
    text = render_context({"session_id": 5, "user_id": "u1", "plan_id": 9,
                           "exercises": [_exercise(effort_flag="too_difficult")]})
    assert "effort_flag too_difficult" in text
    assert "user_id" not in text and "plan_id" not in text and "exercise_id 58" not in text and "rpe" not in text


def test_voice_notes_previous_session_and_cardio_are_rendered():
    text = render_context({
        "client_name": "Teyjus", "is_period": False, "joint_pain": [{"joint": "shoulder", "pain_level": "mild"}],
        "client_voice_feedback": "இன்னைக்கு கஷ்டம்",
        "exercises": [_exercise(client_voice_note="கால் நடுங்குச்சு")],
        "previous_session": {"exercises": [_exercise(effort_flag="too_easy", set_logs=[
            {"set_number": 1, "completed_reps": 20}, {"set_number": 2, "completed_reps": 15}])], "cardio_rating": None},
        "cardio": {"rating": "easy", "what_happened": None},
    })
    assert "client_name: Teyjus" in text and "is_period: no" in text
    assert "joint_pain: shoulder (mild)" in text
    assert "client_voice_feedback: இன்னைக்கு கஷ்டம்" in text
    assert "  client_voice_note: கால் நடுங்குச்சு" in text
    assert "- standing wall plank | prescribed_reps 20,20 | set_logs 20, 15 | effort_flag too_easy" in text
    assert "- rating: easy" in text and "what_happened" not in text


def test_unknown_fields_are_still_sent():
    assert "something_new: 3" in render_context({"something_new": 3})


def test_history_becomes_one_thread_per_topic():
    threads = history_threads(_history())
    knee = next(t for t in threads if t["joint"] == "knee")
    # Four knee questions over three sessions -> one thread.
    assert knee["times_asked"] == 3
    assert knee["asked"] == "Follow up on her knee during cardio."      # newest intent, English only
    assert knee["newest_ask_unanswered"] is True
    assert knee["last_answer"] == "Comes and goes; leg feels stronger."  # latest real answer
    # A joint thread keeps every earlier distinct answer.
    assert knee["earlier_answers"] == [{"date": "2026-11-18", "answer": "Osteoarthritis; mild pain all day when walking."}]


def test_general_questions_group_per_workout_type_with_one_earlier_answer():
    threads = history_threads(_history())
    general = [t for t in threads if not t["joint"] and not t["exercise"]]
    assert len(general) == 1 and general[0]["workout_type"] == "cardio" and general[0]["times_asked"] == 2
    assert general[0]["last_answer"] == "No other problems."
    assert general[0]["earlier_answers"] == [{"date": "2026-11-19", "answer": "Knee pain in one leg since yesterday."}]


def test_a_never_answered_topic_says_so():
    [thread] = history_threads([{"date": "2026-11-24", "workout_type": "strength", "questions": [
        {"intent": "Was the new row clear?", "exercise": "Band Row", "joint": None, "answer": None}]}])
    assert thread["last_answer"] == "never answered"


def test_history_is_rendered_as_lines_without_the_tamil_wording():
    text = render_context({"previous_questions_and_answers": _history()})
    assert "previous_questions_and_answers (one line per topic, newest first):" in text
    assert ("- [knee] asked 3x, last 2026-11-24: Follow up on her knee during cardio. -> answer: Comes and goes; "
            "leg feels stronger. (newest ask unanswered) | earlier (2026-11-18): Osteoarthritis; "
            "mild pain all day when walking.") in text
    assert "முட்டி" not in text
