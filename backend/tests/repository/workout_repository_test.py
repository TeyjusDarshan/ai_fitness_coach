"""Tests for WorkoutRepository.list_exercises."""
from unittest.mock import MagicMock

from backend.repository.workout_repository import WorkoutRepository


def test_list_exercises_orders_by_name_and_normalizes_rows():
    client = MagicMock()
    query = client.table.return_value.select.return_value
    query.order.return_value.execute.return_value.data = [{
        "id": 3,
        "name": "Band Row",
        "movement_types": {"name": "pull"},
        "orientation": "horizontal",
        "dominant": True,
        "equipment": {"name": "resistance bands"},
        "exercise_loaded_joints": [{"joints": {"name": "shoulder"}}, {"joints": {"name": "elbow"}}],
        "min_reps": 8,
        "max_reps": 15,
        "avoid_if": None,
        "video_url": None,
    }]

    exercises = WorkoutRepository(client=client).list_exercises()

    client.table.assert_called_once_with("exercises")
    query.order.assert_called_once_with("name")
    assert exercises == [{
        "id": 3,
        "name": "Band Row",
        "movement_type": "pull",
        "orientation": "horizontal",
        "dominant": True,
        "equipment": ["resistance bands"],
        "loaded_joints": ["shoulder", "elbow"],
        "min_reps": 8,
        "max_reps": 15,
        "is_time_based": False,
        "avoid_if": "",
        "video_url": "",
    }]
