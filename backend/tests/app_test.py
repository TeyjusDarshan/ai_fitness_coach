"""Tests for the PWA's session endpoints (POST /api/sessions/<session_id>/start
and /complete, plus the scheduled-date lock shared with set/RPE logging) and
the dashboard.

Supabase is mocked (see conftest.app_module): the plan_repo methods these
endpoints call are swapped for MagicMocks so these tests exercise only the
endpoints' own logic, not the repository's Supabase queries.
"""
from datetime import date
from unittest.mock import MagicMock

import pytest

TODAY = date(2026, 10, 13)


@pytest.fixture(autouse=True)
def fixed_today(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "app_today", lambda: TODAY)


def _summary(plan_completed=False):
    return {
        "session_id": 42,
        "day_number": 2,
        "exercises_completed": 3,
        "total_exercises": 3,
        "sets_completed": 9,
        "total_sets": 9,
        "total_time_seconds": 1800,
        "plan_completed": plan_completed,
    }


def _session_42(app_module, monkeypatch, owner="usr_1", scheduled_date="2026-10-13", completed_at=None):
    monkeypatch.setattr(app_module.plan_repo, "get_session", MagicMock(return_value={
        "id": 42,
        "plan_id": 7,
        "day_number": 2,
        "scheduled_date": scheduled_date,
        "completed_at": completed_at,
        "plans": {"user_id": owner, "plan_type": "3_day", "completed": False},
    }))


# --- complete ------------------------------------------------------------------

def test_complete_session_success_returns_summary(app_module, sign_in, monkeypatch):
    _session_42(app_module, monkeypatch)
    summary = _summary()
    monkeypatch.setattr(app_module.plan_repo, "complete_session", MagicMock(return_value=summary))

    response = sign_in("usr_1").post("/api/sessions/42/complete")

    assert response.status_code == 200
    assert response.get_json() == summary
    app_module.plan_repo.complete_session.assert_called_once_with(42)


def test_complete_session_not_found_returns_404(app_module, sign_in, monkeypatch):
    monkeypatch.setattr(app_module.plan_repo, "get_session", MagicMock(return_value=None))
    monkeypatch.setattr(app_module.plan_repo, "complete_session", MagicMock())

    response = sign_in("usr_1").post("/api/sessions/999/complete")

    assert response.status_code == 404
    app_module.plan_repo.complete_session.assert_not_called()


def test_complete_session_repo_failure_returns_500(app_module, sign_in, monkeypatch):
    _session_42(app_module, monkeypatch)
    monkeypatch.setattr(
        app_module.plan_repo, "complete_session", MagicMock(side_effect=RuntimeError("db unreachable"))
    )

    response = sign_in("usr_1").post("/api/sessions/42/complete")

    assert response.status_code == 500


# --- start + scheduled-date lock -------------------------------------------------

def test_start_session_on_its_date_starts_it(app_module, sign_in, monkeypatch):
    _session_42(app_module, monkeypatch, scheduled_date="2026-10-13")
    monkeypatch.setattr(app_module.plan_repo, "start_session", MagicMock(return_value={"id": 42}))

    response = sign_in("usr_1").post("/api/sessions/42/start")

    assert response.status_code == 200
    app_module.plan_repo.start_session.assert_called_once_with(42, False)


@pytest.mark.parametrize("gender, body, expected", [
    ("female", {"is_period": True}, True),
    ("female", {"is_period": False}, False),
    ("female", {"is_period": "yes"}, False),
    ("female", {}, False),
    ("male", {"is_period": True}, False),
    ("other", {"is_period": True}, False),
    (None, {"is_period": True}, False),
])
def test_start_session_honours_is_period_only_for_women(app_module, sign_in, monkeypatch, gender, body, expected):
    _session_42(app_module, monkeypatch, scheduled_date="2026-10-13")
    monkeypatch.setattr(app_module.plan_repo, "start_session", MagicMock(return_value={"id": 42}))
    monkeypatch.setattr(app_module.plan_repo, "get_gender", MagicMock(return_value=gender))

    response = sign_in("usr_1").post("/api/sessions/42/start", json=body)

    assert response.status_code == 200
    app_module.plan_repo.start_session.assert_called_once_with(42, expected)


@pytest.mark.parametrize("method, path, body, repo_method", [
    ("post", "/api/sessions/42/start", None, "start_session"),
    ("patch", "/api/sessions/42/exercises/7/sets/1", {"completed_reps": 10}, "log_set"),
    ("patch", "/api/sessions/42/exercises/7/rpe", {"rpe": 8}, "log_rpe"),
    ("post", "/api/sessions/42/complete", None, "complete_session"),
])
def test_uncompleted_session_after_its_date_is_missed(app_module, sign_in, monkeypatch, method, path, body, repo_method):
    _session_42(app_module, monkeypatch, scheduled_date="2026-10-12")
    monkeypatch.setattr(app_module.plan_repo, repo_method, MagicMock())

    response = getattr(sign_in("usr_1"), method)(path, json=body)

    assert response.status_code == 409
    assert response.get_json() == {
        "error": "This workout was missed.",
        "scheduled_date": "2026-10-12",
        "missed": True,
    }
    getattr(app_module.plan_repo, repo_method).assert_not_called()


def test_completed_session_after_its_date_can_still_be_reopened(app_module, sign_in, monkeypatch):
    _session_42(app_module, monkeypatch, scheduled_date="2026-10-12", completed_at="2026-10-12T10:30:00+00:00")
    monkeypatch.setattr(app_module.plan_repo, "complete_session", MagicMock(return_value=_summary()))

    assert sign_in("usr_1").post("/api/sessions/42/complete").status_code == 200


@pytest.mark.parametrize("method, path, body, repo_method", [
    ("post", "/api/sessions/42/start", None, "start_session"),
    ("patch", "/api/sessions/42/exercises/7/sets/1", {"completed_reps": 10}, "log_set"),
    ("patch", "/api/sessions/42/exercises/7/rpe", {"rpe": 8}, "log_rpe"),
    ("post", "/api/sessions/42/complete", None, "complete_session"),
])
def test_session_before_its_date_is_locked(app_module, sign_in, monkeypatch, method, path, body, repo_method):
    _session_42(app_module, monkeypatch, scheduled_date="2026-10-14")
    monkeypatch.setattr(app_module.plan_repo, repo_method, MagicMock())

    response = getattr(sign_in("usr_1"), method)(path, json=body)

    assert response.status_code == 409
    assert response.get_json() == {
        "error": "This workout opens on Wed 14 Oct.",
        "scheduled_date": "2026-10-14",
    }
    getattr(app_module.plan_repo, repo_method).assert_not_called()


# --- dashboard -------------------------------------------------------------------

def _schedule_day(day_number, is_rest_day, session_id=None, scheduled_date=None):
    return {
        "day_number": day_number,
        "day_label": f"Day {day_number}",
        "split_name": "Rest" if is_rest_day else "Full Body",
        "is_rest_day": is_rest_day,
        "session_id": session_id,
        "scheduled_date": scheduled_date,
        "primary": [],
        "secondary": [],
    }


def test_dashboard_dates_and_locks_each_day(app_module, sign_in, monkeypatch):
    sessions = {
        1: {"id": 11, "scheduled_date": "2026-10-12", "started_at": "x", "completed_at": "y"},
        3: {"id": 13, "scheduled_date": "2026-10-14", "started_at": None, "completed_at": None},
    }
    plan = {
        "plan_type": "3_day",
        "plan_selection_reason": None,
        "medical_clearance_warning": None,
        "coach_notes": None,
        "safety_summary": None,
        "schedule": [
            _schedule_day(1, False, 11, "2026-10-12"),
            _schedule_day(2, True),
            _schedule_day(3, False, 13, "2026-10-14"),
        ],
    }
    monkeypatch.setattr(
        app_module.plan_repo,
        "get_unfinished_plan",
        MagicMock(return_value={"id": 7, "completed": False, "plan": plan, "sessions": sessions, "workouts": []}),
    )
    monkeypatch.setattr(app_module.plan_repo, "get_profile", MagicMock(return_value={}))
    monkeypatch.setattr(app_module.plan_repo, "get_previous_plan_workouts", MagicMock(return_value=[]))

    response = sign_in("usr_1").get("/api/users/usr_1/dashboard")

    assert response.status_code == 200
    data = response.get_json()
    assert data["plan_id"] == 7
    days = [(d["day_number"], d["session_id"], d["date"], d["status"], d["locked"]) for d in data["days"]]
    assert days == [
        (1, 11, "2026-10-12", "completed", False),
        (2, None, "2026-10-13", "rest", False),
        (3, 13, "2026-10-14", "next", True),
    ]


def test_dashboard_marks_a_missed_day_and_moves_next_past_it(app_module, sign_in, monkeypatch):
    sessions = {
        1: {"id": 11, "scheduled_date": "2026-10-12", "started_at": "x", "completed_at": None},
        2: {"id": 12, "scheduled_date": "2026-10-13", "started_at": None, "completed_at": None},
        4: {"id": 14, "scheduled_date": "2026-10-15", "started_at": None, "completed_at": None},
    }
    plan = {
        "plan_type": "4_day",
        "plan_selection_reason": None,
        "medical_clearance_warning": None,
        "coach_notes": None,
        "safety_summary": None,
        "schedule": [
            _schedule_day(1, False, 11, "2026-10-12"),
            _schedule_day(2, False, 12, "2026-10-13"),
            _schedule_day(3, True),
            _schedule_day(4, False, 14, "2026-10-15"),
        ],
    }
    monkeypatch.setattr(
        app_module.plan_repo,
        "get_unfinished_plan",
        MagicMock(return_value={"id": 7, "completed": False, "plan": plan, "sessions": sessions, "workouts": []}),
    )
    monkeypatch.setattr(app_module.plan_repo, "get_profile", MagicMock(return_value={}))
    monkeypatch.setattr(app_module.plan_repo, "get_previous_plan_workouts", MagicMock(return_value=[]))

    data = sign_in("usr_1").get("/api/users/usr_1/dashboard").get_json()

    assert [(d["day_number"], d["status"], d["locked"]) for d in data["days"]] == [
        (1, "missed", False),
        (2, "next", False),
        (3, "rest", False),
        (4, "upcoming", True),
    ]


# --- dashboard workout panels ------------------------------------------------------

def _workout(session_id, plan_id, scheduled_date, completed_at=None, started_at=None, name="Full Body"):
    return {
        "session_id": session_id,
        "plan_id": plan_id,
        "day_number": session_id % 10,
        "name": name,
        "scheduled_date": scheduled_date,
        "started_at": started_at,
        "completed_at": completed_at,
        "exercises": [],
    }


def _dashboard_with_workouts(app_module, sign_in, monkeypatch, workouts, previous=()):
    plan = {
        "plan_type": "4_day",
        "plan_selection_reason": None,
        "medical_clearance_warning": None,
        "coach_notes": None,
        "safety_summary": None,
        "schedule": [],
    }
    monkeypatch.setattr(
        app_module.plan_repo,
        "get_unfinished_plan",
        MagicMock(return_value={"id": 7, "completed": False, "plan": plan, "sessions": {}, "workouts": workouts}),
    )
    monkeypatch.setattr(app_module.plan_repo, "get_profile", MagicMock(return_value={}))
    monkeypatch.setattr(app_module.plan_repo, "get_previous_plan_workouts", MagicMock(return_value=list(previous)))
    monkeypatch.setattr(app_module.plan_repo, "count_completed_sessions", MagicMock(return_value=3))
    response = sign_in("usr_1").get("/api/users/usr_1/dashboard")
    assert response.status_code == 200
    return response.get_json()["workouts"]


def _panels(workouts):
    return [(w["session_id"], w["status"], w["date"], w["is_next"], w["can_start"]) for w in workouts]


def test_dashboard_workouts_show_last_two_past_then_every_scheduled_one(app_module, sign_in, monkeypatch):
    # TODAY is Tue 2026-10-13.
    workouts = _dashboard_with_workouts(app_module, sign_in, monkeypatch, [
        _workout(11, 7, "2026-10-10", completed_at="2026-10-10T04:00:00+00:00"),
        _workout(12, 7, "2026-10-11"),
        # 19:00 UTC on the 12th is 00:30 IST on the 13th: shown on the 13th.
        _workout(13, 7, "2026-10-12", completed_at="2026-10-12T19:00:00+00:00"),
        _workout(14, 7, "2026-10-13", started_at="2026-10-13T03:00:00+00:00"),
        _workout(15, 7, "2026-10-15"),
    ])

    assert _panels(workouts) == [
        (12, "missed", "2026-10-11", False, False),
        (13, "completed", "2026-10-13", False, False),
        (14, "scheduled", "2026-10-13", True, True),
        (15, "scheduled", "2026-10-15", False, False),
    ]
    app_module.plan_repo.get_previous_plan_workouts.assert_not_called()


def test_dashboard_workouts_reach_back_into_the_previous_plan(app_module, sign_in, monkeypatch):
    workouts = _dashboard_with_workouts(
        app_module, sign_in, monkeypatch,
        [_workout(21, 7, "2026-10-14"), _workout(22, 7, "2026-10-15")],
        previous=[
            _workout(1, 6, "2026-10-08", completed_at="2026-10-08T04:00:00+00:00"),
            _workout(2, 6, "2026-10-09", completed_at="2026-10-09T04:00:00+00:00"),
            # Never done and dated after today: the coach closed plan 6 early.
            _workout(3, 6, "2026-10-14"),
        ],
    )

    assert _panels(workouts) == [
        (2, "completed", "2026-10-09", False, False),
        (3, "missed", "2026-10-14", False, False),
        (21, "scheduled", "2026-10-14", True, False),
        (22, "scheduled", "2026-10-15", False, False),
    ]
    app_module.plan_repo.get_previous_plan_workouts.assert_called_once_with("usr_1", 7)


def test_dashboard_workouts_mark_todays_and_carry_their_duration(app_module, sign_in, monkeypatch):
    workouts = _dashboard_with_workouts(app_module, sign_in, monkeypatch, [
        _workout(13, 7, "2026-10-13", started_at="2026-10-13T03:00:00+00:00",
                 completed_at="2026-10-13T03:40:00+00:00"),
        _workout(15, 7, "2026-10-15"),
    ])

    assert [(w["session_id"], w["is_today"], w["duration_seconds"]) for w in workouts] == [
        (13, True, 2400),
        (15, False, None),
    ]


def test_dashboard_gives_25_points_per_completed_workout(app_module, sign_in, monkeypatch):
    _dashboard_with_workouts(app_module, sign_in, monkeypatch, [])
    count = app_module.plan_repo.count_completed_sessions

    body = sign_in("usr_1").get("/api/users/usr_1/dashboard").get_json()

    assert body["points"] == 75
    count.assert_called_with("usr_1")


# --- past workouts ----------------------------------------------------------------

def _history_entry(session_id, status, shown_date):
    return {
        **_workout(session_id, 7, shown_date),
        "status": status,
        "date": shown_date,
        "duration_seconds": 1800 if status == "completed" else None,
        "analysis": "coach text",
        "analysis_audio_url": "https://audio",
        "has_feedback": True,
    }


@pytest.fixture
def past_history(app_module, monkeypatch):
    # Newest first, as get_user_workout_history returns them; TODAY is 2026-10-13.
    past = [
        _history_entry(5, "completed", "2026-10-13"),
        _history_entry(4, "missed", "2026-10-11"),
        _history_entry(3, "completed", "2026-10-09"),
        _history_entry(2, "completed", "2026-10-07"),
        _history_entry(1, "completed", "2026-10-05"),
    ]
    history = MagicMock(return_value={"scheduled": [], "past": past})
    monkeypatch.setattr(app_module.plan_repo, "get_user_workout_history", history)
    return history


@pytest.mark.parametrize("query, expected_ids", [
    ("", [5, 4]),
    ("?offset=2&limit=2", [3, 2]),
    ("?offset=4&limit=2", [1]),
    ("?offset=9", []),
])
def test_past_workouts_are_paged_newest_first_with_totals(sign_in, past_history, query, expected_ids):
    response = sign_in("usr_1").get(f"/api/users/usr_1/past-workouts{query}")

    assert response.status_code == 200
    body = response.get_json()
    assert [w["session_id"] for w in body["workouts"]] == expected_ids
    assert (body["total"], body["completed"], body["missed"]) == (5, 4, 1)


def test_past_workouts_drop_coach_only_fields_and_mark_today(sign_in, past_history):
    [today, missed] = sign_in("usr_1").get("/api/users/usr_1/past-workouts").get_json()["workouts"]

    for workout in (today, missed):
        assert not {"analysis", "analysis_audio_url", "has_feedback"} & workout.keys()
        assert (workout["is_next"], workout["can_start"]) == (False, False)
    assert (today["is_today"], today["duration_seconds"]) == (True, 1800)
    assert missed["is_today"] is False


@pytest.mark.parametrize("query, expected", [("?limit=0", 1), ("?limit=500", 5)])
def test_past_workouts_limit_is_clamped(sign_in, past_history, query, expected):
    body = sign_in("usr_1").get(f"/api/users/usr_1/past-workouts{query}").get_json()
    assert len(body["workouts"]) == expected


@pytest.mark.parametrize("query", ["?offset=-1", "?offset=abc", "?limit=x"])
def test_past_workouts_reject_bad_paging(sign_in, past_history, query):
    assert sign_in("usr_1").get(f"/api/users/usr_1/past-workouts{query}").status_code == 400


def test_past_workouts_of_another_user_are_forbidden(sign_in, past_history):
    assert sign_in("usr_1").get("/api/users/usr_2/past-workouts").status_code == 403
    past_history.assert_not_called()


# --- voice feedback ---------------------------------------------------------------

@pytest.fixture
def storage(app_module, monkeypatch):
    stub = MagicMock()
    stub.create_signed_url.return_value = "https://signed.example/session_42.webm?token=abc"
    monkeypatch.setattr(app_module, "feedback_storage", lambda: stub)
    monkeypatch.setattr(app_module.plan_repo, "set_feedback_audio_path", MagicMock())
    return stub


def _upload(client, data=b"voice", mimetype="audio/webm;codecs=opus", field="audio"):
    import io

    return client.post(
        "/api/sessions/42/feedback-audio",
        data={field: (io.BytesIO(data), "feedback", mimetype)} if field else {},
        content_type="multipart/form-data",
    )


def test_feedback_upload_stores_the_recording_and_records_its_path(app_module, sign_in, monkeypatch, storage):
    _session_42(app_module, monkeypatch, completed_at="2026-10-13T10:00:00+00:00")

    response = _upload(sign_in("usr_1"))

    assert response.status_code == 200
    assert response.get_json() == {"feedback_audio_path": "session_42.webm"}
    storage.store.assert_called_once_with(b"voice", "session_42.webm", "audio/webm")
    app_module.plan_repo.set_feedback_audio_path.assert_called_once_with(42, "session_42.webm")
    storage.remove.assert_not_called()


def test_rerecording_in_another_format_removes_the_old_file(app_module, sign_in, monkeypatch, storage):
    _session_42(app_module, monkeypatch)
    session = app_module.plan_repo.get_session.return_value
    session["feedback_audio_path"] = "session_42.webm"

    response = _upload(sign_in("usr_1"), mimetype="audio/mp4")

    assert response.get_json() == {"feedback_audio_path": "session_42.m4a"}
    storage.remove.assert_called_once_with("session_42.webm")


@pytest.mark.parametrize("kwargs, status", [
    ({"field": None}, 400),                       # no file
    ({"data": b""}, 400),                         # empty
    ({"mimetype": "video/mp4"}, 415),             # not audio we store
    ({"data": b"x" * (4 * 1024 * 1024 + 1)}, 413),  # too big
])
def test_feedback_upload_rejects_bad_files(app_module, sign_in, monkeypatch, storage, kwargs, status):
    _session_42(app_module, monkeypatch)

    response = _upload(sign_in("usr_1"), **kwargs)

    assert response.status_code == status
    storage.store.assert_not_called()


def test_feedback_upload_to_another_users_session_is_refused(app_module, sign_in, monkeypatch, storage):
    _session_42(app_module, monkeypatch, owner="usr_2")

    response = _upload(sign_in("usr_1"))

    assert response.status_code == 403
    storage.store.assert_not_called()


def test_feedback_upload_storage_failure_returns_500_without_recording_a_path(app_module, sign_in, monkeypatch, storage):
    _session_42(app_module, monkeypatch)
    storage.store.side_effect = RuntimeError("bucket unreachable")

    response = _upload(sign_in("usr_1"))

    assert response.status_code == 500
    app_module.plan_repo.set_feedback_audio_path.assert_not_called()


def test_feedback_link_is_a_signed_url_for_the_stored_path(app_module, sign_in, monkeypatch, storage):
    _session_42(app_module, monkeypatch)
    app_module.plan_repo.get_session.return_value["feedback_audio_path"] = "session_42.webm"

    response = sign_in("usr_1").get("/api/sessions/42/feedback-audio")

    assert response.status_code == 200
    assert response.get_json() == {"url": "https://signed.example/session_42.webm?token=abc"}
    storage.create_signed_url.assert_called_once_with("session_42.webm", 3600)


def test_feedback_link_without_a_recording_is_404(app_module, sign_in, monkeypatch, storage):
    _session_42(app_module, monkeypatch)

    assert sign_in("usr_1").get("/api/sessions/42/feedback-audio").status_code == 404


def test_coach_can_get_a_feedback_link_with_the_admin_key(app_module, monkeypatch, storage):
    _session_42(app_module, monkeypatch)
    app_module.plan_repo.get_session.return_value["feedback_audio_path"] = "session_42.webm"
    monkeypatch.setenv("ADMIN_API_KEY", "k")
    client = app_module.app.test_client()

    assert client.get("/api/admin/sessions/42/feedback-audio").status_code == 401
    ok = client.get("/api/admin/sessions/42/feedback-audio", headers={"X-Admin-Key": "k"})

    assert ok.status_code == 200
    assert ok.get_json()["url"].startswith("https://signed.example/")
