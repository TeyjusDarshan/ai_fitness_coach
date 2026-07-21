import json
import os
from typing import Optional

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()


class WorkoutRepository:
    """Queries the exercise library tables in Supabase."""

    def __init__(self, client: Optional[Client] = None):
        if client is not None:
            self.client = client
        else:
            url = os.environ.get("SUPABASE_URL")
            key = os.environ.get("SUPABASE_KEY")
            self.client = create_client(url, key)

    def search_exercises(
        self,
        movement_pattern_ids: Optional[list[int]] = None,
        equipment_ids: Optional[list[int]] = None,
        body_part_ids: Optional[list[int]] = None,
        exercise_type_ids: Optional[list[int]] = None,
        muscle_group_ids: Optional[list[int]] = None,
    ) -> list[dict]:
        """Search active exercises, filtered by any combination of the given lookup id lists.

        Params left as None/empty are not applied as filters. movement_pattern_ids,
        equipment_ids, exercise_type_ids and muscle_group_ids each match an exercise
        that has ANY of the given ids. body_part_ids is a negative filter: it
        excludes exercises that load ANY of the given body parts.

        Each result includes the exercise's own columns plus its related movement
        pattern, equipment, body parts, muscle groups and exercise types.
        """
        # A join table only needs `!inner` when we filter on one of its columns,
        # otherwise it stays a left join so exercises without a match still appear.
        equipment_join = "exercise_equipment!inner" if equipment_ids else "exercise_equipment"
        muscle_group_join = "exercise_muscle_groups!inner" if muscle_group_ids else "exercise_muscle_groups"
        exercise_type_join = "exercise_exercise_types!inner" if exercise_type_ids else "exercise_exercise_types"

        select_str = f"""
            *,
            movement_patterns(*),
            {equipment_join}(is_required, equipment(*)),
            exercise_body_part_load(load_level, body_parts(*)),
            {muscle_group_join}(role, muscle_groups(*)),
            {exercise_type_join}(is_primary, exercise_types(*))
        """

        query = self.client.table("exercises").select(select_str).eq("active", True)

        if movement_pattern_ids:
            query = query.in_("movement_pattern_id", movement_pattern_ids)
        if equipment_ids:
            query = query.in_("exercise_equipment.equipment_id", equipment_ids)
        if muscle_group_ids:
            query = query.in_("exercise_muscle_groups.muscle_group_id", muscle_group_ids)
        if exercise_type_ids:
            query = query.in_("exercise_exercise_types.exercise_type_id", exercise_type_ids)
        if body_part_ids:
            # PostgREST embedded filters can only require a related row, not
            # exclude one, so exclusion needs its own lookup of matching ids.
            loaded = (
                self.client.table("exercise_body_part_load")
                .select("exercise_id")
                .in_("body_part_id", body_part_ids)
                .execute()
            )
            excluded_ids = [row["exercise_id"] for row in loaded.data]
            if excluded_ids:
                query = query.not_.in_("id", excluded_ids)

        res =  query.execute().data
        return res

    def get_all_movement_patterns(self) -> list[dict]:
        return self.client.table("movement_patterns").select("*").execute().data

    def get_all_muscle_groups(self) -> list[dict]:
        return self.client.table("muscle_groups").select("*").execute().data

    def get_all_equipment(self) -> list[dict]:
        return self.client.table("equipment").select("*").execute().data

    def get_all_exercise_types(self) -> list[dict]:
        return self.client.table("exercise_types").select("*").execute().data

    def get_all_body_parts(self) -> list[dict]:
        return self.client.table("body_parts").select("*").execute().data


if __name__ == "__main__":
    repo = WorkoutRepository()
    results = repo.search_exercises(
        movement_pattern_ids=[1, 2, 10, 8],
        equipment_ids=[2, 4, 5],
        # body_part_ids=[2],
        exercise_type_ids=[1],
    )
    print(json.dumps(results, indent=2))
