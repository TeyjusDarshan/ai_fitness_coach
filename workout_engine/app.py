import gradio as gr

from repository.workout_repository import WorkoutRepository

repo = WorkoutRepository()

ANY = "Any"

movement_patterns = repo.get_all_movement_patterns()
equipment = repo.get_all_equipment()
body_parts = repo.get_all_body_parts()
exercise_types = repo.get_all_exercise_types()
muscle_groups = repo.get_all_muscle_groups()


def _choices(rows):
    return [row["name"] for row in rows]


def _ids_for(rows, names):
    if not names:
        return None
    name_set = set(names)
    return [row["id"] for row in rows if row["name"] in name_set]


def search(movement_pattern_names, equipment_names, body_part_names, exercise_type_names, muscle_group_names):
    return repo.search_exercises(
        movement_pattern_ids=_ids_for(movement_patterns, movement_pattern_names),
        equipment_ids=_ids_for(equipment, equipment_names),
        body_part_ids=_ids_for(body_parts, body_part_names),
        exercise_type_ids=_ids_for(exercise_types, exercise_type_names),
        muscle_group_ids=_ids_for(muscle_groups, muscle_group_names),
    )


with gr.Blocks(title="Workout Search") as demo:
    gr.Markdown("# Workout Search")

    with gr.Row():
        movement_pattern_dd = gr.Dropdown(choices=_choices(movement_patterns), multiselect=True, label="Movement Pattern")
        equipment_dd = gr.Dropdown(choices=_choices(equipment), multiselect=True, label="Equipment")
        body_part_dd = gr.Dropdown(choices=_choices(body_parts), multiselect=True, label="Body Part (excluded)")
        exercise_type_dd = gr.Dropdown(choices=_choices(exercise_types), multiselect=True, label="Exercise Type")
        muscle_group_dd = gr.Dropdown(choices=_choices(muscle_groups), multiselect=True, label="Muscle Group")

    search_btn = gr.Button("Search")
    results = gr.JSON(label="Exercises")

    search_btn.click(
        fn=search,
        inputs=[movement_pattern_dd, equipment_dd, body_part_dd, exercise_type_dd, muscle_group_dd],
        outputs=results,
    )

if __name__ == "__main__":
    demo.launch()
