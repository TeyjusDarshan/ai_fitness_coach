# AI Fitness Coach

## Database Schema (Supabase)

Project: `khwrrvmejvrupokvfwvf` ("AI powered Fitness trainer", region `ap-northeast-1`, Postgres 17.6).

> ⚠️ **RLS is disabled on every table below.** All 11 tables are exposed to the `anon`/`authenticated` roles — anyone with the publishable key can read or write every row. This is only tolerable while the data is public reference content (exercise library); revisit before adding user-specific data. Remediation SQL is available on request — don't apply it blind, since enabling RLS with no policies blocks all access.

### Entity overview

`exercises` is the hub table. Everything else is either a lookup table (movement_patterns, muscle_groups, equipment, body_parts, exercise_types) or a many-to-many join between `exercises` and a lookup table.

```
movement_patterns ─┐
                    ├─< exercises >─┬─< exercise_equipment      >─ equipment
muscle_groups ──────┼───────────────┤
                    │               ├─< exercise_body_part_load >─ body_parts
                    │               ├─< exercise_muscle_groups  >─ muscle_groups
                    │               ├─< exercise_exercise_types >─ exercise_types
                    │               └─< exercise_progressions   >─ exercises (self-referential: easier/harder variant)
```

### Lookup tables

| Table | Rows | Columns | Notes |
|---|---|---|---|
| `movement_patterns` | 12 | `id` PK, `name` unique, `description` | e.g. squat, hinge, push |
| `muscle_groups` | 20 | `id` PK, `name` unique, `body_region` | `body_region` ∈ `upper, lower, core, full_body` |
| `equipment` | 6 | `id` PK, `name` unique, `is_home_friendly` bool (default true) | |
| `body_parts` | 8 | `id` PK, `name` unique | |
| `exercise_types` | 3 | `id` PK, `name` unique | `name` ∈ `strength, mobility, cardio` |

### `exercises` (64 rows) — hub table

| Column | Type | Notes |
|---|---|---|
| `id` | int4 PK | |
| `name` | varchar | |
| `description` | text, nullable | |
| `movement_pattern_id` | int4, nullable, FK → `movement_patterns.id` | |
| `difficulty_level` | int2 | check: `>= 1` |
| `is_bodyweight` | bool, default `true` | |
| `is_unilateral` | bool, default `false` | |
| `video_url` | text, nullable | |
| `instructions` | text, nullable | |
| `default_sets` | int2, nullable | |
| `default_rep_low` / `default_rep_high` | int2, nullable | rep range |
| `created_at` | timestamptz, default `now()` | |
| `active` | bool, default `true` | soft-delete/visibility flag |

### Join tables (many-to-many, composite PK)

| Table | Rows | PK | Extra column |
|---|---|---|---|
| `exercise_equipment` | 76 | (`exercise_id`, `equipment_id`) | `is_required` bool, default `true` |
| `exercise_body_part_load` | 147 | (`exercise_id`, `body_part_id`) | `load_level` int2, check `1–3` |
| `exercise_muscle_groups` | 213 | (`exercise_id`, `muscle_group_id`) | `role` varchar, check ∈ `primary, secondary` |
| `exercise_exercise_types` | 74 | (`exercise_id`, `exercise_type_id`) | `is_primary` bool, default `true` |

### `exercise_progressions` (104 rows) — self-referential

| Column | Type | Notes |
|---|---|---|
| `id` | int4 PK | |
| `exercise_id` | int4, nullable, FK → `exercises.id` | base exercise |
| `related_exercise_id` | int4, nullable, FK → `exercises.id` | linked variant |
| `direction` | varchar, check ∈ `easier, harder` | direction of `related_exercise_id` relative to `exercise_id` |
| `reason` | varchar, nullable | |

All FK columns above (`movement_pattern_id`, `exercise_id`, `related_exercise_id`, etc.) are nullable with no explicit `ON DELETE` action, so deletes on parent rows will be blocked by default rather than cascading — check before deleting from `exercises` or any lookup table.
