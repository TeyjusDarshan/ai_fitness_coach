import csv
import json
import os
from typing import Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "..", "..", "utilities", "workout_builder", "data")
EXERCISES_CSV = os.path.join(DATA_DIR, "exercises.csv")
RELATIONSHIPS_CSV = os.path.join(DATA_DIR, "relationships.csv")


def _split(value):
    return [part for part in (value or "").split(";") if part]


def _to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class ExerciseCsvRepository:
    """Reads the exercise library produced by the workout_builder utility (CSV, not Supabase)."""

    def __init__(self, exercises_csv: str = EXERCISES_CSV, relationships_csv: str = RELATIONSHIPS_CSV):
        self.exercises = self._load_exercises(exercises_csv)
        self.relationships = self._load_relationships(relationships_csv)
        self._exercises_by_id = {ex["id"]: ex for ex in self.exercises}

    @staticmethod
    def _load_exercises(path):
        exercises = []
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                exercises.append({
                    "id": _to_int(row.get("id")),
                    "name": row.get("name", ""),
                    "movement_type": row.get("movement_type", ""),
                    "orientation": row.get("orientation", ""),
                    "dominant": row.get("dominant") == "true",
                    "equipment": _split(row.get("equipment")),
                    "loaded_joints": _split(row.get("loaded_joints")),
                    "min_reps": _to_int(row.get("min_reps")),
                    "max_reps": _to_int(row.get("max_reps")),
                    "avoid_if": row.get("avoid_if", ""),
                })
        return exercises

    @staticmethod
    def _load_relationships(path):
        relationships = []
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                relationships.append({
                    "id": _to_int(row.get("id")),
                    "from_exercise_id": _to_int(row.get("from_exercise_id")),
                    "to_exercise_id": _to_int(row.get("to_exercise_id")),
                    "type": row.get("type", ""),
                    "reason": row.get("reason", ""),
                })
        return relationships

    def get_exercises_by_movement(
        self, movement_type: str, dominant: bool, orientation: Optional[str] = None
    ) -> list[dict]:
        """Return every exercise whose movement_type and dominant flag match the given values.

        orientation, if given, must be "vertical" or "horizontal" and further
        restricts the results to exercises with that orientation.
        """
        if orientation is not None and orientation not in ("vertical", "horizontal"):
            raise ValueError('orientation must be "vertical" or "horizontal"')

        return [
            ex for ex in self.exercises
            if ex["movement_type"] == movement_type
            and ex["dominant"] == dominant
            and (orientation is None or ex["orientation"] == orientation)
        ]

    def get_progressions_or_regressions(self, exercise_id: int, direction: str) -> Optional[list[dict]]:
        """Return the progression/regression exercises linked to exercise_id.

        direction must be "progression" or "regression". Returns None if this
        exercise has no relationships of that direction.
        """
        if direction not in ("progression", "regression"):
            raise ValueError('direction must be "progression" or "regression"')

        matches = [
            rel for rel in self.relationships
            if rel["from_exercise_id"] == exercise_id and rel["type"] == direction
        ]
        if not matches:
            return None

        results = []
        for rel in matches:
            exercise = self._exercises_by_id.get(rel["to_exercise_id"])
            if exercise is not None:
                results.append({**exercise, "reason": rel["reason"]})
        return results or None


if __name__ == "__main__":
    repo = ExerciseCsvRepository()
    print(json.dumps(repo.get_exercises_by_movement("squat", True), indent=2))
    print(json.dumps(repo.get_exercises_by_movement("push", True, orientation="horizontal"), indent=2))
    print(json.dumps(repo.get_progressions_or_regressions(1, "progression"), indent=2))
    print(json.dumps(repo.get_progressions_or_regressions(1, "regression"), indent=2))
