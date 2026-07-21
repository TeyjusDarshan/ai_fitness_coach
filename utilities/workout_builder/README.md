# Workout Builder

A local utility for creating exercises and mapping their relationships on a
drag-and-drop board. No dependencies — Python 3 standard library only.

## Run

```sh
python3 app.py
```

Then open <http://localhost:8765>.

## Screens

1. **Create Exercises** — form with name, movement type (squat / hinge / lunge /
   push / pull / carry), Dominant vs Light, equipment (bodyweight, resistance
   bands, other free-text), loaded joints, min/max reps, and a "who should
   avoid this" description. Created exercises show in a table with delete.
2. **Relationship Board** — all exercises listed on the left, filterable by
   movement type and Dominant/Light. Drag a card onto the whiteboard, then drag
   from its ● handle to another card to connect them. Click an arrow to set its
   type:
   - **alternatives** (blue, dashed, double-headed)
   - **progression** (green) — default reason "RIR > 3 and hit rep ceiling"
   - **regression** (orange) — pick reason(s) via checkboxes: Lack of form,
     Lack of strength

## Persistence

Every change auto-saves to two CSVs in `data/`:

- `exercises.csv` — one row per exercise, including board position
  (`on_board`, `board_x`, `board_y`) so the whiteboard restores on reopen.
  Multi-value fields (`equipment`, `loaded_joints`) are `;`-separated.
- `relationships.csv` — one row per arrow: `from_exercise_id`,
  `to_exercise_id`, `type`, `reason` (`;`-separated for multiple regression
  reasons).

State is reloaded from these files every time the app starts.
