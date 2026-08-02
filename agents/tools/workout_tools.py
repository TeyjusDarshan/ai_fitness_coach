from typing import Optional

from langchain_core.tools import tool

from backend.repository.workout_repository import WorkoutRepository

repo = WorkoutRepository()


@tool
def search_exercises_by_movement(
    movement_type: str, dominant: bool, orientation: Optional[str] = None
) -> list[dict]:
    """Fetch candidate exercises for one day-template slot.

    This is the ONLY way to find exercises — there is no full catalog dump
    available anywhere else, so call this once per slot you need to fill.

    Args:
        movement_type: One of "squat", "hinge", "lunge", "push", "pull",
            "rotation", "carry" — must match the slot's `movement_type`
            exactly.
        dominant: Must match the slot's `dominant` flag exactly (True for
            every Primary slot, False for every Secondary slot).
        orientation: "horizontal" or "vertical" if the slot specifies one
            (push/pull slots only), otherwise omit this argument entirely.

    Returns:
        Every matching exercise, each with: id, name, movement_type,
        orientation, dominant, equipment (list), loaded_joints (list),
        min_reps, max_reps, avoid_if. Apply the safety and equipment
        guardrails to these results yourself before picking one.
    """
    return repo.get_exercises_by_movement(movement_type, dominant, orientation)


@tool
def get_alternate_exercises(exercise_id: int, direction: str) -> Optional[list[dict]]:
    """Look up easier/harder variants of an exercise for safe substitution.

    Use this only when every default candidate for a slot (from
    search_exercises_by_movement) was excluded by a safety filter (e.g.
    equipment or an excluded joint) and you need a substitute. direction
    must be "regression" (easier variant, e.g. for a client without medical
    clearance or with a joint restriction) or "progression" (harder variant,
    e.g. the client has outgrown the default pick). Returns None if no such
    relationship exists for this exercise.
    """
    return repo.get_progressions_or_regressions(exercise_id, direction)


WORKOUT_TOOLS_V1 = [search_exercises_by_movement, get_alternate_exercises]
