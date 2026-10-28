# Workout Builder

A local utility for creating exercises and mapping their relationships on a
drag-and-drop board. It reads and writes the exercise library **directly in
Supabase**: there are no local data files.

## Run

From the repo root, with the project's virtualenv (it uses the `supabase`
package and `SUPABASE_URL` / `SUPABASE_KEY` from the repo's `.env`):

```sh
.venv/bin/python utilities/workout_builder/app.py
```

Then open <http://localhost:8765>.

## Screens

1. **Create Exercises** — form with name, movement type, Dominant vs Light,
   equipment (bodyweight, resistance bands, other free-text; one is stored
   per exercise), loaded joints with a **load** for each (high / mid / low /
   no load), min/max reps (seconds for a **timed hold** such as a plank), and
   a "who should avoid this" description. Created exercises show in a table
   with edit and delete.
2. **Relationship Board** — all exercises listed on the left, filterable by
   movement type and Dominant/Light. Drag a card onto the whiteboard, then drag
   from its ● handle to another card to connect them. Click an arrow to set its
   type:
   - **progression** (green) — default reason "RIR > 3 and hit rep ceiling"
   - **regression** (orange) — pick reason(s) via checkboxes: Lack of form,
     Lack of strength

## Saving

Every change auto-saves straight to Supabase (`exercises`,
`exercise_loaded_joints`, `exercise_relationships`; new movement types or
equipment names are added to their lookup tables). The page sends its whole
state; the server compares it with what it last loaded and writes only the
differences. The status in the header shows "Saved to Supabase ✓".

An exercise that's already used in clients' workout plans can't be deleted
(the database won't allow it): the board says so and reloads. Take it off the
board instead. Plan progression follows only one progression and one "lack of
strength" regression arrow per exercise, so don't draw more than that.

Only one person should edit at a time: two open boards would overwrite each
other's changes.
