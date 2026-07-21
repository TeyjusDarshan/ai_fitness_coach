from typing import Optional

from langchain_core.tools import tool

from repository.workout_repository import WorkoutRepository

repo = WorkoutRepository()


@tool
def search_exercises(
    movement_pattern_ids: Optional[list[int]] = None,
    equipment_ids: Optional[list[int]] = None,
    body_part_ids: Optional[list[int]] = None,
    exercise_type_ids: Optional[list[int]] = None,
    muscle_group_ids: Optional[list[int]] = None,
) -> list[dict]:
    """Search the exercise library and return matching active exercises.

    Use this to find exercises that fit a user's goals, e.g. "chest exercises
    with dumbbells" or "knee-friendly lower body strength moves". All filters
    are optional and combine as an AND across categories; any filter left out
    is simply not applied. Every id must come from the corresponding
    get_all_* lookup tool (get_all_movement_patterns, get_all_equipment,
    get_all_body_parts, get_all_exercise_types, get_all_muscle_groups) -
    never guess an id.

    Each returned exercise includes its own fields (name, description,
    difficulty_level, instructions, default sets/reps, etc.) plus its related
    movement pattern, equipment, body parts, muscle groups, and exercise
    types.

    Args:
        movement_pattern_ids: Match exercises whose movement pattern is ANY
            of these movement_patterns.id values (e.g. squat, hinge, push).
        equipment_ids: Match exercises that use ANY of these equipment.id
            values (e.g. dumbbell, barbell, bodyweight).
        body_part_ids: EXCLUDE exercises that load ANY of these body_parts.id
            values. Use this to avoid stressing an injured or sore body part
            (e.g. exclude "knee" for someone with knee pain).
        exercise_type_ids: Match exercises whose type is ANY of these
            exercise_types.id values (strength, mobility, cardio).
        muscle_group_ids: Match exercises that target ANY of these
            muscle_groups.id values (primary or secondary).

    Returns:
        A list of exercise records matching the given filters.
    """
    return repo.search_exercises(
        movement_pattern_ids=movement_pattern_ids,
        equipment_ids=equipment_ids,
        body_part_ids=body_part_ids,
        exercise_type_ids=exercise_type_ids,
        muscle_group_ids=muscle_group_ids,
    )


@tool
def get_all_movement_patterns() -> list[dict]:
    """List every movement pattern (id, name, description), e.g. squat, hinge, push, pull.

    Call this to look up the movement_pattern_ids to pass into
    search_exercises when a user asks for exercises by movement pattern.
    """
    return repo.get_all_movement_patterns()


@tool
def get_all_muscle_groups() -> list[dict]:
    """List every muscle group (id, name, body_region), e.g. quadriceps, chest, core.

    body_region is one of upper, lower, core, full_body. Call this to look up
    the muscle_group_ids to pass into search_exercises when a user asks for
    exercises that target specific muscles.
    """
    return repo.get_all_muscle_groups()


@tool
def get_all_equipment() -> list[dict]:
    """List every piece of equipment (id, name, is_home_friendly).

    Call this to look up the equipment_ids to pass into search_exercises
    when a user asks for exercises using (or restricted to) specific
    equipment, e.g. only bodyweight/home-friendly equipment.
    """
    return repo.get_all_equipment()


@tool
def get_all_exercise_types() -> list[dict]:
    """List every exercise type (id, name): strength, mobility, cardio.

    Call this to look up the exercise_type_ids to pass into search_exercises
    when a user asks for a specific kind of training.
    """
    return repo.get_all_exercise_types()


@tool
def get_all_body_parts() -> list[dict]:
    """List every body part (id, name) that an exercise can load/stress.

    Call this to look up the body_part_ids to EXCLUDE via search_exercises,
    e.g. when a user has an injury or wants to avoid loading a given body
    part.
    """
    return repo.get_all_body_parts()


WORKOUT_TOOLS = [
    search_exercises,
    get_all_movement_patterns,
    get_all_muscle_groups,
    get_all_equipment,
    get_all_exercise_types,
    get_all_body_parts,
]
