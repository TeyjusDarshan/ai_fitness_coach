import json
import os
from typing import Optional

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()


def _to_str(value) -> str:
    return value if value is not None else ""


class WorkoutRepository:
    """Queries the exercise library tables in Supabase.

    Exposes the same interface as ExerciseCsvRepository so callers can swap
    between the CSV-backed and Supabase-backed repositories interchangeably.
    """

    def __init__(self, client: Optional[Client] = None):
        if client is not None:
            self.client = client
        else:
            url = os.environ.get("SUPABASE_URL")
            key = os.environ.get("SUPABASE_KEY")
            self.client = create_client(url, key)

    def get_exercises_by_movement(
        self, movement_type: str, dominant: bool, orientation: Optional[str] = None
    ) -> list[dict]:
        """Return every exercise whose movement_type and dominant flag match the given values.

        orientation, if given, must be "vertical" or "horizontal" and further
        restricts the results to exercises with that orientation.
        """
        if orientation is not None and orientation not in ("vertical", "horizontal"):
            raise ValueError('orientation must be "vertical" or "horizontal"')

        query = (
            self.client.table("exercises")
            .select("*, movement_types!inner(name), equipment(name), exercise_loaded_joints(joints(name))")
            .eq("movement_types.name", movement_type)
            .eq("dominant", dominant)
        )
        if orientation is not None:
            query = query.eq("orientation", orientation)

        rows = query.execute().data
        return [self._normalize_exercise(row) for row in rows]

    def get_progressions_or_regressions(self, exercise_id: int, direction: str) -> Optional[list[dict]]:
        """Return the progression/regression exercises linked to exercise_id.

        direction must be "progression" or "regression". Returns None if this
        exercise has no relationships of that direction.
        """
        if direction not in ("progression", "regression"):
            raise ValueError('direction must be "progression" or "regression"')

        rows = (
            self.client.table("exercise_relationships")
            .select(
                "reason, "
                "exercises!exercise_relationships_to_exercise_id_fkey"
                "(*, movement_types(name), equipment(name), exercise_loaded_joints(joints(name)))"
            )
            .eq("from_exercise_id", exercise_id)
            .eq("type", direction)
            .execute()
            .data
        )
        if not rows:
            return None

        results = []
        for row in rows:
            exercise = row.get("exercises")
            if exercise is not None:
                normalized = self._normalize_exercise(exercise)
                normalized["reason"] = _to_str(row.get("reason"))
                results.append(normalized)
        return results or None

    @staticmethod
    def _normalize_exercise(row: dict) -> dict:
        """Reshape a raw Supabase exercise row into ExerciseCsvRepository's flat shape."""
        movement_type = row.get("movement_types")
        equipment = row.get("equipment")
        joints = [
            link["joints"]["name"]
            for link in (row.get("exercise_loaded_joints") or [])
            if link.get("joints")
        ]
        return {
            "id": row["id"],
            "name": _to_str(row.get("name")),
            "movement_type": _to_str(movement_type["name"] if movement_type else None),
            "orientation": _to_str(row.get("orientation")),
            "dominant": bool(row.get("dominant")),
            "equipment": [equipment["name"]] if equipment else [],
            "loaded_joints": joints,
            "min_reps": row.get("min_reps"),
            "max_reps": row.get("max_reps"),
            "avoid_if": _to_str(row.get("avoid_if")),
        }


if __name__ == "__main__":
    repo = WorkoutRepository()
    print(json.dumps(repo.get_exercises_by_movement("squat", True), indent=2))
    print(json.dumps(repo.get_exercises_by_movement("push", True, orientation="horizontal"), indent=2))
    print(json.dumps(repo.get_progressions_or_regressions(1, "progression"), indent=2))
    print(json.dumps(repo.get_progressions_or_regressions(1, "regression"), indent=2))
