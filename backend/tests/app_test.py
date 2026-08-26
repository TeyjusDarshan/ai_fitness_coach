"""Tests for POST /api/sessions/<session_id>/days/<day_number>/complete.

Supabase and Kafka are mocked (see conftest.app_module): plan_repo.complete_day
and kafka_producer.send_workout_complete_event are swapped for MagicMocks so
these tests exercise only the endpoint's own logic, not the repository's
Supabase queries or a real Kafka broker.
"""
from unittest.mock import MagicMock


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


def test_complete_day_success_publishes_kafka_event(app_module, monkeypatch):
    summary = _summary()
    monkeypatch.setattr(app_module.plan_repo, "complete_day", MagicMock(return_value=summary))
    monkeypatch.setattr(app_module.kafka_producer, "send_workout_complete_event", MagicMock())

    client = app_module.app.test_client()
    response = client.post("/api/sessions/42/days/2/complete")

    assert response.status_code == 200
    assert response.get_json() == summary
    app_module.plan_repo.complete_day.assert_called_once_with(42, 2)
    app_module.kafka_producer.send_workout_complete_event.assert_called_once_with(42, 2)


def test_complete_day_session_not_found_returns_404_and_skips_kafka(app_module, monkeypatch):
    monkeypatch.setattr(app_module.plan_repo, "complete_day", MagicMock(return_value=None))
    monkeypatch.setattr(app_module.kafka_producer, "send_workout_complete_event", MagicMock())

    client = app_module.app.test_client()
    response = client.post("/api/sessions/999/days/1/complete")

    assert response.status_code == 404
    app_module.kafka_producer.send_workout_complete_event.assert_not_called()


def test_complete_day_repo_failure_returns_500_and_skips_kafka(app_module, monkeypatch):
    monkeypatch.setattr(
        app_module.plan_repo, "complete_day", MagicMock(side_effect=RuntimeError("db unreachable"))
    )
    monkeypatch.setattr(app_module.kafka_producer, "send_workout_complete_event", MagicMock())

    client = app_module.app.test_client()
    response = client.post("/api/sessions/42/days/2/complete")

    assert response.status_code == 500
    app_module.kafka_producer.send_workout_complete_event.assert_not_called()


def test_complete_day_kafka_failure_does_not_fail_request(app_module, monkeypatch):
    summary = _summary()
    monkeypatch.setattr(app_module.plan_repo, "complete_day", MagicMock(return_value=summary))
    monkeypatch.setattr(
        app_module.kafka_producer,
        "send_workout_complete_event",
        MagicMock(side_effect=RuntimeError("kafka broker unreachable")),
    )

    client = app_module.app.test_client()
    response = client.post("/api/sessions/42/days/2/complete")

    assert response.status_code == 200
    assert response.get_json() == summary
