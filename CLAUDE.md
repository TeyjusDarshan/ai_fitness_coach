# AI Fitness Coach

## Database Schema (Supabase)

Project: `khwrrvmejvrupokvfwvf` ("AI powered Fitness trainer", region `ap-northeast-1`, Postgres 17.6).

> ⚠️ **RLS is disabled on every table below except `cardio_exercises`.** The other 25 tables are exposed to the `anon`/`authenticated` roles — anyone with the publishable key can read or write every row. This was originally tolerable while the data was public reference content (exercise library); that condition has now been **triggered**, not just theoretical — `user_profiles`, `plans`, `sessions`, `session_exercises`, `session_exercise_set_logs`, `session_exercise_rpe`, `session_cardio_logs`, `user_joint_pain`, `user_period_logs`, `session_analysis`, `workout_comments`, `session_clarifications`, `clarification_replies`, `coach_suggestion_runs`, and `exercise_suggestions` hold real per-user data (generated profiles, weekly plans, scheduled workout days and their progress, prescribed exercises, per-set rep logs, RPE, per-step cardio logs, reported joint pain, logged period days, generated LLM workout summaries, health notes taken from voice feedback, WhatsApp replies and phone numbers, AI Coach suggestions) and are still exposed with no RLS. This is a known, accepted gap, not an oversight. Remediation SQL is available on request — don't apply it blind, since enabling RLS with no policies blocks all access.
>
> The one exception is `cardio_exercises` (the cardio circuit, library data): RLS is **enabled** with a read-only `cardio_exercises read` policy for `anon`/`authenticated`, so the app can read it but only the dashboard / service-role key can change it. Cardio progression state lives on `sessions` rows and is as exposed as the rest.
>
> This includes the passkey-auth tables (`user_passkeys`, `auth_challenges`, `auth_sessions`, `passkey_enrollment_tokens`): the API-level passkey sign-in is only as strong as the secrecy of the publishable key, since anyone holding it can insert an `auth_sessions` row (or their own passkey) for any `user_id` and impersonate that user. Kept this way deliberately (decision 2026-09-27) because the backend's `SUPABASE_KEY` is the publishable key. The fix is to switch the backend (and `workout_analysis_consumer`) to the secret/service-role key, which bypasses RLS, and then enable RLS on these tables.

> The exercise-library schema (`movement_types`, `equipment`, `joints`, `exercises`, `exercise_loaded_joints`, `exercise_relationships`) is edited in the Workout Builder board (`utilities/workout_builder`, `.venv/bin/python utilities/workout_builder/app.py` → http://localhost:8765), which reads and writes these tables in Supabase directly — there is no CSV copy or migration step any more (the old `exercises.csv` / `relationships.csv` / `migrate_exercises_to_supabase.py` flow was removed; git history has them). The board saves its whole state on each change and the server writes only the differences; it refuses to delete an exercise that `session_exercises` still references (no-cascade FK) — take it off the board instead. It offers only `progression`/`regression` links, matching the table's check. Plan progression follows only one progression and one lack-of-strength regression edge per exercise, so avoid drawing more. Populated as of this writing: 66 exercises, 203 joint links, 108 relationships.

### Entity overview

`exercises` is the hub table. `movement_types`, `equipment`, and `joints` are lookup tables. `exercise_loaded_joints` is a many-to-many join between `exercises` and `joints`. `exercise_relationships` is a self-referential edge table (progression/regression links between exercises). `user_profiles` holds one generated profile per user; `user_joint_pain` holds one row per (user, joint) the user has reported pain for. Workouts form a three-level hierarchy: `plans` holds one row per weekly workout plan for a user; `sessions` holds one row per **training day** of a plan (its `day_number`, `scheduled_date`, and start/completion timestamps); `session_exercises` is a join table between `sessions` and `exercises` recording the prescribed sets/reps per exercise slot of that day. `session_exercise_set_logs` and `session_exercise_rpe` track per-set rep completion and per-exercise RPE against a `session_exercises` row; `session_analysis` holds one LLM-generated Tanglish summary per session, written by the standalone `workout_analysis_consumer` service (see below), which also writes `workout_comments` (structured coach notes from the client's voice notes and replies) and `session_clarifications` / `clarification_replies` (the questions asked after the summary and her WhatsApp answers) — see "Voice-feedback agent" below. Cardio days are `sessions` rows with `kind = 'cardio'` (no `session_exercises`); they run the whole `cardio_exercises` circuit — see "Cardio days" below. The passkey-auth tables — `user_passkeys`, `auth_sessions`, `passkey_enrollment_tokens`, `auth_challenges` — hang off `user_profiles` (see "Passkey authentication tables" below).

```
movement_types ─┐
                ├─< exercises >─┬─< exercise_loaded_joints >─ joints
equipment ──────┘               └─< exercise_relationships >─ exercises (self-referential: from/to)
                                 └─< session_exercises >─ sessions >─ plans >─ user_profiles ─< user_joint_pain >─ joints
                                       ├─< session_exercise_set_logs   │
                                       └─< session_exercise_rpe        └─< session_analysis (one per session)
```

`plans.parent_plan_id` links each auto-progressed plan to the plan it was progressed from.

### Lookup tables

| Table | Columns | Notes |
|---|---|---|
| `movement_types` | `id` PK, `name` unique | squat, push, pull, hinge, lunge, carry, rotation |
| `equipment` | `id` PK, `name` unique | bodyweight, resistance bands |
| `joints` | `id` PK, `name` unique | ankle, knee, hip, spine, shoulder, elbow, wrist |

### `exercises` — hub table

Edited in the Workout Builder board; its per-exercise loaded joints (with a high/mid/low/nil load each) are stored in `exercise_loaded_joints`.

| Column | Type | Notes |
|---|---|---|
| `id` | int4 PK | `GENERATED BY DEFAULT AS IDENTITY` — CSV IDs can be inserted explicitly |
| `name` | varchar | |
| `movement_type_id` | int4, nullable, FK → `movement_types.id` | no cascade |
| `orientation` | varchar, nullable | check ∈ `horizontal, vertical` (NULL where CSV blank) |
| `dominant` | bool, nullable | |
| `equipment_id` | int4, nullable, FK → `equipment.id` | single-valued per exercise; no cascade |
| `min_reps` / `max_reps` | int2, nullable | rep range |
| `is_time_based` | bool, default `false` | true for static holds measured in **seconds** rather than reps — currently Superman, Static split squat, standing wall plank, Knee plank, full plank, Side Plank, Dead-Bug. For these, `min_reps`/`max_reps` (and the sets' `reps` in `session_exercises`) are seconds. Set with the Workout Builder form's "Timed hold" checkbox. Returned on dashboard exercise entries; the PWA runs these with the timed flow (`TimedExerciseScreen`: countdown, hold timer, rest, then the same feedback screen as rep exercises) and logs seconds held as `completed_reps`. Progression steps them +5 s (correct) / +10 s (easy) / −5 s (hard) instead of ±1/2 reps (`TIMED_*_STEP`); the analysis consumer marks them `unit: seconds` |
| `avoid_if` | text, nullable | contraindications |
| `on_board` | bool, default `true` | |
| `board_x` / `board_y` | float8, nullable | board coordinates |
| `created_at` | timestamptz, default `now()` | |

### `exercise_loaded_joints` — many-to-many join

Composite PK. Edited in the Workout Builder form (a load picker per ticked joint). `joint_load` (high / mid / low / nil) feeds the injury multiplier in progression.

| Column | Type | Notes |
|---|---|---|
| `exercise_id` | int4, FK → `exercises.id` | `ON DELETE CASCADE` |
| `joint_id` | int4, FK → `joints.id` | no cascade |

PK: (`exercise_id`, `joint_id`).

### `exercise_relationships` — self-referential edges

Drawn as arrows on the Workout Builder board. Each row links a `from` exercise to a `to` exercise with a direction.

| Column | Type | Notes |
|---|---|---|
| `id` | int4 PK | `GENERATED BY DEFAULT AS IDENTITY` |
| `from_exercise_id` | int4, FK → `exercises.id` | `ON DELETE CASCADE` |
| `to_exercise_id` | int4, FK → `exercises.id` | `ON DELETE CASCADE` |
| `type` | varchar | check ∈ `progression, regression` |
| `reason` | text, nullable | e.g. "Lack of strength", "RIR > 3 and hit rep ceiling" |

Unique: (`from_exercise_id`, `to_exercise_id`, `type`).

### `user_profiles` — generated client profile per user

Populated via `WorkoutPlanRepository.upsert_user_profile` by either the Flask `/workout-plan` endpoint (`backend/app.py`) or the coach admin flow's `POST /api/admin/users/profile` (`backend/controllers/admin_plan_controller.py`, driven by the PWA's `/admin` screen), both of which run `generate_user_profile` (preprocessor agent) on the coach's free-form client text. **Upsert-by-`user_id`, not versioned** — each new generation for a user overwrites the previous profile; there is no history table.

| Column | Type | Notes |
|---|---|---|
| `user_id` | text PK | caller-supplied id (e.g. `"usr_10235"`), not a Supabase-auth UUID |
| `profile` | jsonb | full generated profile (`demographics`, `goals`, `experience`, `health`, `availability`, etc. — see `agents/mock_data_v1.py` for the shape) |
| `created_at` | timestamptz, default `now()` | |
| `updated_at` | timestamptz, default `now()` | bumped on every upsert |
| `name` | text, nullable | client display name, entered by the coach on the `/admin` intake step (required there; optional `name` on `POST /workout-plan`). Shown in place of `user_id` wherever the user is named: the PWA (returned by `/api/auth/me` and sign-in), the coach share message, the admin screens, the passkey's display name, and the analysis consumer's greeting (`client_name`). Only overwritten when a new name is given. NULL for users created before it existed — the PWA falls back to `user_id` |
| `gender` | text, nullable | check ∈ `male, female, other`. Set by the coach on the `/admin` intake step (`POST /api/admin/users/profile`, only overwritten when given); returned by `/api/auth/me` and sign-in. Women (`female`) are asked "are you on your period?" before a fresh workout starts (see `sessions.is_period`). NULL for users created before it existed — no prompt. Independent of the LLM-extracted `profile.demographics.sex` |
| `webauthn_user_handle` | text, nullable, unique | random 32-byte WebAuthn `user.id` (base64url), created on first passkey enrollment by `AuthRepository.get_or_create_user_handle`; shared by all of the user's passkeys and checked against `userHandle` at sign-in |

### `user_joint_pain` — reported pain per (user, joint)

Populated by `WorkoutPlanRepository.upsert_joint_pain` / `delete_joint_pain` via `POST /api/users/<user_id>/joint-pain` and `DELETE /api/users/<user_id>/joint-pain/<joint_id>` (`backend/app.py`). Read by `_fetch_user_joint_pain` and fed into `get_injury_multiplier` to reduce load on exercises hitting a painful joint during progression.

| Column | Type | Notes |
|---|---|---|
| `id` | int4 PK | `GENERATED BY DEFAULT AS IDENTITY` |
| `user_id` | text, FK → `user_profiles.user_id` | `ON DELETE CASCADE` |
| `joint_id` | int4, FK → `joints.id` | no cascade |
| `pain_level` | varchar | check ∈ `mild, moderate, severe` |
| `created_at` | timestamptz, default `now()` | |
| `updated_at` | timestamptz, default `now()` | bumped on every upsert |

Unique: (`user_id`, `joint_id`) — makes `upsert_joint_pain` an idempotent upsert; re-reporting pain for a joint already on file overwrites it rather than duplicating.

### `plans` — one row per weekly workout plan

Populated by `WorkoutPlanRepository.create_plan` (brand-new plan — either agent-generated via `/workout-plan`, or hand-built by the coach in the `/admin` planner and saved via `POST /api/admin/users/<user_id>/initial-plan`, which refuses with 409 if the user already has an unfinished plan and sets `plan_selection_reason` to "Built manually by coach") or `WorkoutPlanRepository.create_progressed_plan` (progress-plan flow — carries forward a completed plan's sessions and exercises). Plan-level metadata only — the training days live in `sessions`. (This table was named `sessions` before the 2026-10-11 plans/sessions split.)

| Column | Type | Notes |
|---|---|---|
| `id` | int4 PK | `GENERATED BY DEFAULT AS IDENTITY` |
| `user_id` | text, FK → `user_profiles.user_id` | `ON DELETE CASCADE` |
| `parent_plan_id` | int4, nullable, FK → `plans.id` | self-referential; `ON DELETE SET NULL`. `NULL` for a brand-new plan (`create_plan`); set to the source plan's `id` when created via `create_progressed_plan` (auto-progress on completion, or `POST /api/users/<user_id>/progress-plan`) |
| `plan_type` | varchar | `3_day` \| `4_day` |
| `plan_selection_reason` | text, nullable | |
| `medical_clearance_warning` | text, nullable | |
| `coach_notes` | text, nullable | |
| `safety_summary` | jsonb, nullable | `{excluded_movements, excluded_joints, excluded_equipment}` |
| `completed` | bool, default `false` | |
| `created_at` | timestamptz, default `now()` | |
| `completed_at` | timestamptz, nullable | set when marked completed |

Partial unique index `plans_one_unfinished_per_user` on `(user_id)` where `completed = false` — enforces at most one unfinished plan per user, matching the endpoints' short-circuit logic (`POST /workout-plan` returns the existing unfinished plan instead of generating a new one) and guarding against duplicate inserts from a racing/retried request.

### `sessions` — one row per training day of a plan

One row per non-rest day of a plan's `DAY_TEMPLATES[plan_type]` schedule (rest days have no row). Created alongside the plan by `create_plan` / `create_progressed_plan`. Drives the PWA dashboard and the end-of-day summary screen's Total Time stat. `GET /api/users/<user_id>/dashboard` returns `workouts` — one panel per session: the last two past ones (completed or missed, reaching into the previous completed plan via `get_previous_plan_workouts` early in a new plan), then every scheduled one, each with `status` (completed / missed / scheduled), a display `date` (completion date in `APP_TIMEZONE`, else `scheduled_date`), `is_next`, `can_start` (scheduled for today) and its exercises with set logs and RPE, for the panel's View screen (`/workout/<session_id>`). Each panel also carries `is_today` (completed or scheduled today — the PWA's Today card) and `duration_seconds`. The PWA dashboard shows the Today card (or, on a rest day, the next workout), then collapsible Upcoming and Past sections; Past lists every past workout across all plans, two at a time, through `GET /api/users/<user_id>/past-workouts?offset=&limit=` (own user only; newest first via `get_user_workout_history`, coach-only fields dropped; `limit` clamped 1–20, default 2; returns `total`/`completed`/`missed` for the section's counts). The dashboard also returns `points` — 25 (`POINTS_PER_WORKOUT`) per completed session across all of the user's plans (`count_completed_sessions`; derived, not stored, so missed sessions earn nothing and period sessions count). The PWA turns them into plant levels (`frontend/src/plant3d/levels.ts`: levels 1–4 cost 25 each, 5–8 50 each, 9–11 100 each, so 600 points / 24 workouts is fully grown at level 11) and shows them at the top of the dashboard as a 3D potted plant (`PlantScene`, three.js, ported from the `plant/` prototype, one growth step per level; lazily loaded) plus a level bar. That top part is fixed and only the workouts below it scroll. After a workout the PWA goes cool-down video → `/day/:n/grow` → `/day/:n/summary`: the grow screen is what calls `POST /api/sessions/<id>/complete` (whose response also carries `points` and `points_earned` — 25 the first time, 0 when re-completing), shows the plant full screen earning the points and growing a stage on a level-up, then hands the result to the summary screen (router state) so it isn't completed twice; the summary screen still completes on its own after a reload. With nothing earned it goes straight to the summary. The step last shown is kept in `localStorage` so a new level grows in with sparkles. It also still returns the per-day `days` list (rest / completed / missed / next / upcoming, plus `locked`) that the in-workout screens address by `day_number`.

| Column | Type | Notes |
|---|---|---|
| `id` | int4 PK | `GENERATED BY DEFAULT AS IDENTITY` — the id the PWA's `/api/sessions/<session_id>/…` routes and the WhatsApp share message ("Session ID: …") use |
| `plan_id` | int4, FK → `plans.id` | `ON DELETE CASCADE` |
| `day_number` | int2 | check 1–7, matches `DAY_TEMPLATES[plan_type].schedule[].day_number` |
| `scheduled_date` | date | the day this session opens. `create_plan`: coach-chosen start date + (`day_number` − 1); `create_progressed_plan`: the source plan's same-day session + 7 days, or — if that week would start in the past (the source plan closed late) — the plan starts today |
| `started_at` | timestamptz, nullable | set once, on the first `start_session` call — never overwritten by a later re-entry |
| `completed_at` | timestamptz, nullable | set when the session's summary screen is reached (`complete_session`) |
| `feedback_audio_path` | text, nullable | object path (`session_<id>.<ext>`) of the client's recorded voice feedback in the **private** `voice-feedback` Storage bucket, recorded on the PWA's end-of-day summary screen (`/day/:n/summary`, uploaded when she taps "Share Workout & Voice Note", behind an upload-progress screen, just before WhatsApp opens) via `POST /api/sessions/<id>/feedback-audio` (≤ 4 MB; a re-record overwrites). A path, not a URL: it's read through short-lived signed URLs — `GET /api/sessions/<id>/feedback-audio` (the owner) or `GET /api/admin/sessions/<id>/feedback-audio` (`X-Admin-Key`, for the coach). Bucket access for the publishable key comes from the `voice-feedback app access` policy on `storage.objects`. The analysis consumer also downloads it and transcribes it for the summary prompt (see `session_analysis`) |
| `kind` | varchar, default `'strength'` | check ∈ `strength, cardio`. A cardio session sits on a day `DAY_TEMPLATES` marks as rest (`CARDIO_DAYS`), has no `session_exercises`, and is run by the PWA's `CardioScreen` — see "Cardio days" |
| `cardio_rounds` / `cardio_work_seconds` | int2, nullable | a cardio session's level: rounds of the circuit × seconds per exercise (15–60). Required when `kind = 'cardio'` (`sessions_cardio_level_check`); every cardio session of a plan shares one level |
| `cardio_rating` | varchar, nullable | check ∈ `easy, medium, hard` — how the client said the cardio felt (`PUT /api/sessions/<id>/cardio-rating`, same open/missed lock as the other session writes). Drives next week's cardio level |
| `is_period` | bool, default `false` | set by the first `start_session` when a female user answers "yes" to "are you on your period?" (`POST /api/sessions/<id>/start` with `{"is_period": true}`; ignored for anyone whose `user_profiles.gender` isn't `female`, and never re-applied on resume). On that first start `_apply_period_adjustment` rewrites the session's `session_exercises` rows **in place** to 70% of the planned reps (`PERIOD_REP_FACTOR`), swapping to the "lack of strength" regression — or clamping to `min_reps` when there's no edge — wherever that falls below an exercise's `min_reps`. The originals are not kept. Progression never learns from a period session: `_progression_sources` uses each day's latest non-period session (walking up `parent_plan_id`, at most `MAX_PROGRESSION_HOPS` plans) as the source and the non-period session before it for the two-week hold check; a day with no non-period history carries the period rows forward unchanged. The analysis consumer is told (`is_period`) and skips period sessions as `previous_session`. On a **cardio** session nothing is rewritten: its `cardio_work_seconds` is scaled to 70% when read (see "Cardio days") |
| `created_at` | timestamptz, default `now()` | |

Unique: (`plan_id`, `day_number`). **Scheduled-date lock:** the backend refuses start / set / RPE / complete for a session (409, `_deny_unless_session_open` in `backend/app.py`) while `scheduled_date` is after today in `APP_TIMEZONE` (env, default `Asia/Kolkata`; see `app_today()`). **Missed days (strict):** a session with no `completed_at` whose `scheduled_date` is before today is *missed* (`is_session_missed`) — including one that was started with sets logged but never finished. Missed is derived, not stored (no column, no cron job): a missed session is refused the same way (409, `"missed": true`), shows as `missed` on the dashboard, and `next` moves past it. Once every session of a plan is completed or missed, the plan is closed via `mark_plan_completed` (which auto-progresses it) — either by `complete_session` when the last open session is finished, or lazily by `get_unfinished_plan` the next time anything loads the plan (dashboard, `/workout-plan`, progress-plan, admin), which then returns the new plan. `mark_plan_completed` only matches while `completed = false`, so racing closes progress a plan once. In progression, a missed session's exercises carry forward unchanged (same exercise, same reps) instead of taking the missing-RPE → hard path; reported joint pain still reduces them. Like a period session, a missed one is skipped when looking for the earlier week of the two-week hold, so the streak compares with the last completed week. Replaces the former `session_day_logs` table.

### Cardio days (`cardio_exercises` + cardio `sessions`)

Logic in `backend/cardio.py`. `create_plan` (and `create_progressed_plan`, which also adds them to a plan from before cardio existed) creates one `kind = 'cardio'` session on each of `CARDIO_DAYS[plan_type]` — days 2, 4, 6 for `3_day`, days 3 and 6 for `4_day` (day 7 stays a rest day). `DAY_TEMPLATES` itself is unchanged (the workout agent and the coach planner rely on its rest days); `_reconstruct_plan` / `_workout_entries` overlay those days as `split_name: "Cardio"`, `is_rest_day: false`, `kind: "cardio"`, with a `cardio` block (`rounds`, `work_seconds`, `rating`, rest timings, `estimated_seconds`, and the circuit's `exercises` with public `video_url` / `poster_url`). Everything else — date lock, missed rule, plan close, 25 points on completion — treats them like any session. Women get the same "are you on your period?" prompt on cardio days: a yes sets `is_period` as usual, and each exercise then runs 70% of its planned seconds, rounded, at least 15 s (`CARDIO_PERIOD_FACTOR`, `period_seconds`). That scaling is applied **when the session is read** (`_cardio_block`'s `work_seconds`, with the stored level as `planned_work_seconds`; `complete_session`; the analysis consumer) — `cardio_work_seconds` itself is never rewritten.

**The run:** the same warm-up video as strength days (skipped when resuming a session already started) → 10 s get-ready → each circuit exercise for `work_seconds` (its clip plays muted and looped under a seconds-left ring) → a rest a third as long as the exercise (`exercise_rest_seconds`: 30 s → 10 s, 60 s → 20 s; on a period day, a third of the shorter time) showing the next one → after a round's last exercise a 30 s round rest instead → … → `/day/:n/cardio/rate` (easy / about right / too difficult, "skip" = medium) → the same cool-down video → grow → summary. Not resumable mid-circuit: leaving restarts it. As each exercise and each rest ends, the PWA logs how it went (`PUT /api/sessions/<id>/cardio-log`, see `session_cardio_logs`); the client's View screen and the coach's Monitor clients show it (`CardioLog`), with a "Skipped N" chip on the coach's card.

**Progression (per week, `_cardio_next_level`):** everyone starts at 1 round × 30 s. The week's outcome is the most common `cardio_rating` among its completed cardio sessions, period sessions excluded (unrated counts as medium; ties go to the harder rating; nothing that votes → hold, so a week done entirely on her period keeps its level). Easy → +10 s up to 60, and at 60 s one more round back at 30 s. Hard → −10 s down to 15, and at 15 s one round fewer at 60 s (1 × 15 s is the floor). Medium holds once: it steps up only when the previous counted week (nearest ancestor plan with a completed non-period cardio session, up to `MAX_PROGRESSION_HOPS`) was also medium at the same level.

**`cardio_exercises`** — the circuit, in `position` order: `id` identity PK, `name`, `video_path` / `poster_path` (object paths in the **public** `cardio-videos` Storage bucket, 50 MB limit, mp4/jpeg), `position` int2 unique, `active` bool (inactive rows are left out), `created_at`. Seeded with 10 clips. The clips are re-encoded (720p, no audio) by `utilities/cardio_videos/prepare.sh` and uploaded by `utilities/cardio_videos/upload.py` (needs `SUPABASE_SERVICE_ROLE_KEY` in the environment). The backend caches the circuit for 5 minutes. The analysis consumer gets cardio sessions as `workout_type: "cardio"` with the circuit names, level, rating and a computed `compared_to_last_time`.

### `session_cardio_logs` — what actually happened in a cardio session

One row per exercise per round of a cardio session, written by `WorkoutPlanRepository.log_cardio_step` via `PUT /api/sessions/<id>/cardio-log` (`{round, position, part: "exercise" | "rest", actual_seconds, paused_seconds, skipped}`, same open/missed lock as the other session writes; 400 for a strength session or a step outside the session's rounds × circuit). The PWA sends one as each exercise or rest ends — run out, or via Skip Exercise / Skip Rest — fire-and-forget. The rest after an exercise lives on that exercise's row (after a round's last exercise, the round rest). Read back nested in `PLAN_SESSIONS_SELECT` as the `cardio` block's `log` (ordered) and `log_summary` (`exercises_done`, `exercises_skipped`, `exercises_missing` = planned but never reached, `rests_skipped`, `active_seconds`, `paused_seconds`). Record only: progression still goes by `cardio_rating`.

| Column | Type | Notes |
|---|---|---|
| `id` | int4 PK | `GENERATED BY DEFAULT AS IDENTITY` |
| `session_id` | int4, FK → `sessions.id` | `ON DELETE CASCADE` |
| `round` / `position` | int2 | 1-based round; 0-based place in the circuit |
| `cardio_exercise_id` | int4, nullable, FK → `cardio_exercises.id` | `ON DELETE SET NULL`, indexed |
| `exercise_name` | text | copied in, so history survives circuit changes |
| `planned_seconds` | int2 | set by the server from the session's level (70% on a period day) |
| `actual_seconds` / `paused_seconds` / `skipped` | int2 / int2 / bool, nullable | the exercise: active seconds done, seconds paused, whether Skip Exercise was tapped |
| `rest_planned_seconds` / `rest_actual_seconds` / `rest_paused_seconds` / `rest_skipped` | nullable | the rest after it — null after the final exercise, or when she left first |
| `created_at` / `updated_at` | timestamptz | |

Unique: (`session_id`, `round`, `position`) — each write upserts only its own part's columns (plus the name and planned seconds, so either part can arrive first), and a re-run of the circuit overwrites the earlier attempt.

### `session_exercises` — join table between `sessions` and `exercises`

One row per prescribed exercise slot within a session. Deliberately does **not** duplicate `name`/`movement_type`/`equipment`/`orientation`/`dominant` (joined in from `exercises` at read time) or `day_label`/`split_name`/`is_rest_day` (reconstructed from the fixed `DAY_TEMPLATES[plan_type]` skeleton in `agents/prompts_v1.py` using `plans.plan_type` + `sessions.day_number`).

| Column | Type | Notes |
|---|---|---|
| `id` | int4 PK | `GENERATED BY DEFAULT AS IDENTITY` |
| `session_id` | int4, FK → `sessions.id` | `ON DELETE CASCADE` |
| `exercise_id` | int4, FK → `exercises.id` | no cascade |
| `category` | varchar | check ∈ `primary, secondary` — which slot list this exercise fills |
| `slot_label` | varchar, nullable | e.g. `"Hinge"`, `"Push (Horizontal)"` — echoes the slot label from `DAY_TEMPLATES` |
| `sets` | int2, nullable | |
| `reps` | varchar, nullable | |
| `rep_range` | varchar, nullable | |
| `note` | text, nullable | |
| `feedback_audio_path` | text, nullable | object path (`session_<sid>_exercise_<id>.<ext>`) in the private `voice-feedback` bucket of the client's optional voice note about this exercise, recorded on the PWA's exercise feedback screen and uploaded when she moves on (`POST /api/sessions/<sid>/exercises/<id>/feedback-audio`, same types/size limit as the session note; a re-record overwrites). Returned as `has_feedback` on exercise entries; the coach plays it in Monitor clients via `GET /api/admin/session-exercises/<id>/feedback-audio` (`X-Admin-Key`, signed URL). Transcribed by the analysis consumer (feeds `workout_comments` and the summary), not carried forward by progression |
| `skipped` / `skip_reason` | bool (default `false`) / text, nullable | the coach skipped this exercise for this one workout (accepting an AI Coach "skip" suggestion; restored with `PATCH /api/admin/session-exercises/<id>` `{"skipped": false}`). Left out of `_reconstruct_plan` (her workout run), not counted by `complete_session`, refused by the set/RPE/feedback-audio endpoints, shown as "Skipped by your coach" on her View screen and as Skipped (with Restore) in Monitor clients, and left out of the analysis consumer's context. Progression carries it forward unchanged, like a missed one (`_flatten_session_exercises`); the next week's row is not skipped |
| `created_at` | timestamptz, default `now()` | |

Per-set completion and RPE are tracked in the child tables below rather than on this row.

### `session_exercise_set_logs` — per-set completion within a `session_exercises` row

One row per set actually logged, written via `WorkoutPlanRepository.log_set`. Each `set_number` is its own row (keyed by the unique constraint below), so logging two different sets on the same exercise back to back can't race the way a shared jsonb array could — this replaced an earlier `session_exercises.completed_sets` jsonb boolean array design for that reason.

| Column | Type | Notes |
|---|---|---|
| `id` | int4 PK | `GENERATED BY DEFAULT AS IDENTITY` |
| `session_exercise_id` | int4, FK → `session_exercises.id` | `ON DELETE CASCADE` |
| `set_number` | int2 | 1-indexed, the kth set within that `session_exercises` row (≤ its `sets`) |
| `completed_reps` | int2 | reps actually performed on that set |
| `created_at` | timestamptz, default `now()` | |

Unique: (`session_exercise_id`, `set_number`) — one log row per set, and makes `log_set` an idempotent upsert. `complete_session` treats a `session_exercises` row as fully done once it has as many logged sets as its prescribed `sets`.

### `session_exercise_rpe` — perceived exertion per prescribed exercise

One row per `session_exercises` row, written via `WorkoutPlanRepository.log_rpe` — RPE is logged once per exercise (not per set). In the PWA, after an exercise's sets "Next Exercise" opens an "Exercise Complete!" feedback screen (`/day/:n/exercise/:slot/feedback`): Easier than expected / About right / Too difficult log RPE 6 / 8 / 10, and "Skip this time" logs 8. She can also record an optional voice note there (`session_exercises.feedback_audio_path`). It then goes on to the rest timer, or the cool-down after the last exercise. Timed holds reach the same screen from their "Great Job!" step.

| Column | Type | Notes |
|---|---|---|
| `id` | int4 PK | `GENERATED BY DEFAULT AS IDENTITY` |
| `session_exercise_id` | int4, FK → `session_exercises.id` | `ON DELETE CASCADE` |
| `rpe` | int2 | check 1–10 |
| `created_at` | timestamptz, default `now()` | |

Unique: (`session_exercise_id`) — makes `log_rpe` an idempotent upsert.

### `user_period_logs` — days a user said she was on her period

One row per (user, date) on which a user answered **yes** to "are you on your period?" when starting a workout. Written by `WorkoutPlanRepository._log_period`, called from `start_session` only on a session's first start with `is_period` (so resuming or an ordinary start never logs). Not read by anything yet — it's a record for tracking.

| Column | Type | Notes |
|---|---|---|
| `id` | int4 PK | `GENERATED BY DEFAULT AS IDENTITY` |
| `user_id` | text, FK → `user_profiles.user_id` | `ON DELETE CASCADE` |
| `logged_on` | date | the day she answered yes, in `APP_TIMEZONE` (`app_today()`) |
| `session_id` | int4, nullable, FK → `sessions.id` | the session she answered on; `ON DELETE SET NULL` |
| `created_at` | timestamptz, default `now()` | |

Unique: (`user_id`, `logged_on`) — answering yes on two sessions the same day logs it once (insert ignores the duplicate). Indexed on `session_id`.

### `session_analysis` — LLM-generated Tanglish summary per session

One row per session that's been analyzed. Written by the standalone `workout_analysis_consumer` package (repo root, alongside `backend`/`frontend`) — a Kafka consumer, independent of the Flask app, that listens on the `workout-complete-events` topic. Those events are produced by `backend/kafka_producer` from the WhatsApp webhook (`backend/controllers/whatsapp_webhook_controller.py`) when the client shares a finished workout with the coach: the shared message carries a `Session ID: <sessions.id>` line, and the event payload is `{session_id, phone_number}`. On each event the consumer reads that session's `session_exercises` (with `session_exercise_set_logs` and `session_exercise_rpe` joined in), its plan, the user's `user_profiles.profile`, and their `user_joint_pain`. It transcribes the session's `feedback_audio_path` and every `session_exercises.feedback_audio_path` in parallel (`transcribe_many`; `KAFKA_MAX_POLL_INTERVAL_MS` defaults to 900000 to leave room), each recording with a Sarvam batch speech-to-text job (`stt/`, `saaras:v4`, `ta-IN`, `codemix`; `STT_JOB_TIMEOUT_SECONDS`, default 180) and passes the session transcript as `client_voice_feedback` and each exercise's as that exercise's `client_voice_note`. This is best-effort: a failed transcription is logged and the summary is written without it. It then prompts Claude (`claude-sonnet-5-5`, via the `anthropic` SDK with server-side refusal fallback; a refusal raises `SummaryRefusedError` rather than saving anything) to write (as structured output, `WorkoutSummary`) a one-line greeting/summary in **Tanglish** (no per-exercise commentary) followed by up to 10 clarifying questions — detailed where something needs understanding (a complaint, too hard, unfinished sets, unclear pain, and for too-easy exercises how easy and how many more reps — or seconds for a timed hold — she could have done), short or skipped otherwise, at most one per exercise, exercise names said in English exactly as `exercises.name` (see "Voice-feedback agent") (Tamil-majority, code-switching into English for gym/fitness terms — see `workout_analysis_consumer/prompts.py`), and upserts the result here. If the plan has a `parent_plan_id`, the consumer also fetches the parent plan's session for the **same `day_number`** (its exercises, set logs, RPE and start/completion times) and includes it as `previous_session` context, so the prompt can call out individual- and exercise-specific progress compared to the client's last time on that day of their split (see `AnalysisRepository._fetch_previous_session_context`). If that session was missed, it walks further up `parent_plan_id` (up to `MAX_PREVIOUS_PLAN_HOPS` plans) to the most recent completed one. The voice note is stored as `plan_<plan_id>/day_<day_number>.ogg`.

| Column | Type | Notes |
|---|---|---|
| `id` | int4 PK | `GENERATED BY DEFAULT AS IDENTITY` |
| `session_id` | int4, FK → `sessions.id` | `ON DELETE CASCADE` |
| `analysis` | text | the generated Tanglish summary |
| `audio_url` | text, nullable | URL of the generated voice analysis (TTS audio) for `analysis` |
| `created_at` | timestamptz, default `now()` | |

Unique: (`session_id`) — makes the consumer's write an idempotent upsert, so redelivering an already-processed Kafka message overwrites rather than duplicates. (Was `session_day_analysis`, keyed by plan + day, before the plans/sessions split.)

### Voice-feedback agent (`workout_comments`, `session_clarifications`, `clarification_replies`)

Lives in `workout_analysis_consumer` (`feedback_agent.py`, `feedback_prompts.py`, wired in `main.py`). Claude (`claude-sonnet-5-5`, structured outputs via `client.beta.messages.parse`, server-side refusal fallback) only *proposes* notes; `validate_note` drops any note whose `quote` isn't really in what the client said (case/punctuation/space-insensitive), unlinks exercises not in the session and joints not in `joints`.

**After a workout share** (`_process_message`): the transcripts go to `extract_feedback`, whose notes replace the session's voice-note rows in `workout_comments` (so a redelivered event doesn't duplicate) and update `user_joint_pain` — **overwrite**: within one batch the worst level per joint wins, `pain_resolved` deletes the row, and a later batch simply overwrites (`joint_pain_changes`, `AnalysisRepository.apply_joint_pain`). Notes flagged `urgent` (chest pain, dizziness, …) are logged as warnings. The notes are passed to the summary as `client_feedback_notes`, along with `previous_questions_and_answers` — the questions (both rounds) and answer summaries from her last 8 sessions that had any (`AnalysisRepository.fetch_question_history`, `MAX_QUESTION_HISTORY_SESSIONS`, newest first, current session excluded), which the prompt uses to follow up on unsettled pain or repeated difficulty and to avoid re-asking what she already answered; the summary's questions (priority: unclear pain → why too hard → how easy → new exercise (`is_new`) → missed sets → open "any other discomfort") are validated (`validate_questions`, ids `q1…`, max 10 — `MAX_QUESTIONS` — and only the first question per `session_exercise_id` kept; the prompt asks for every one that applies, not a fixed number) and spoken at the end of the same voice note (`spoken_text`: summary, intro, questions, goodbye — the whole text is what `session_analysis.analysis` stores). The round-1 `session_clarifications` row is saved **before** the audio is sent (and the phone's older open rounds are superseded); if there's no audio, the questions go as a text message.

**Her replies:** the WhatsApp webhook publishes every text or voice message without a `Session ID` line to the `workout-feedback-replies` topic (`{phone_number, whatsapp_message_id, type, text | media_id}`), which the same consumer handles (`_process_reply`): it finds the phone's latest open, unexpired round (none → ignored), records the message in `clarification_replies` (deduped by `whatsapp_message_id`), downloads + stores (`session_<sid>_reply_<reply id>.<ext>` in `voice-feedback`) + transcribes a voice reply, and runs `map_reply`, which maps the answer onto question ids, extracts notes (stored with `source = clarification_reply`, `question_id`, `clarification_reply_id`; same pain rules) and, in round 1 only, may ask at most 2 follow-ups (it gets the same 8-session question history, to ask how an earlier problem compares instead of re-asking it). Follow-ups → round 1 closes (`answered`/`superseded`), a round-2 row opens and they're sent as a voice note (`plan_<plan_id>/day_<n>_followup.ogg`); everything answered → `answered` plus a fixed Tanglish thank-you text; otherwise it just records the answers and waits.

**`workout_comments`** — one row per observation. `id`; `user_id` (FK, cascade); `session_id` (FK, cascade); `session_exercise_id` (nullable FK, cascade — null = about the whole session); `exercise_id` (nullable FK → `exercises`, `ON DELETE SET NULL`, denormalized for per-exercise history); `category` ∈ `difficulty, joint_pain, pain_resolved, discomfort, fatigue, technique, enjoyment, other`; `difficulty` ∈ `too_easy, about_right, too_hard`; `joint_id` (FK → `joints`) / `pain_level` ∈ `mild, moderate, severe`; `urgent` bool; `comment` (English coach note); `quote` (her exact words); `source` ∈ `session_voice_note, exercise_voice_note, clarification_reply`; `clarification_reply_id` (nullable FK, cascade); `question_id`; `created_at`.

**`session_clarifications`** — one row per round of questions. `session_id`, `user_id` (FKs, cascade), `phone_number` (from the share event), `round` (1, or 2 for follow-ups), `questions` jsonb `[{id, text, intent, topic, session_exercise_id, joint}]`, `answers` jsonb `{question_id: {summary, reply_id}}`, `status` ∈ `open, answered, superseded, expired` (expired lazily after `expires_at` = asked + 24 h, WhatsApp's free-form reply window), `asked_at`, `closed_at`. Unique (`session_id`, `round`); a redelivered event re-opens a round only if it has no replies yet.

**`clarification_replies`** — one row per inbound WhatsApp message matched to a round: `clarification_id` (FK, cascade), `whatsapp_message_id` (unique), `message_type` ∈ `text, audio`, `text`, `audio_path`, `transcript`, `processed_at` (set once handled; a processed message is skipped on redelivery).

### AI Coach agent (`coach_suggestion_runs`, `exercise_suggestions`)

Admin-only. In Monitor clients, each **scheduled strength** workout card has an AI coach panel (`frontend/src/screens/admin/CoachSuggestions.tsx`): "Get AI suggestions" calls `POST /api/admin/sessions/<id>/suggestions` (`backend/controllers/admin_coach_agent_controller.py`, `X-Admin-Key`; 409 unless scheduled and strength), which runs the agent **inside the request** (~20–30 s; `claude-opus-5-5`, effort medium, structured output via `client.beta.messages.parse`, server-side refusal fallback, `COACH_AGENT_TIMEOUT_SECONDS` default 55, no retries — 502 on failure). Code in `backend/coach_agent/`:
- `context.py` (`build_context`, reads via `repository.py`'s `CoachAgentRepository` on the plan repo's Supabase client): the client (full profile, joint pain, recent period days, week's coach notes, safety summary); every exercise with min–max, prescribed sets and per-set reps, loaded joints with load, `avoid_if`, and its progression/regression options from `exercise_relationships` (the only allowed swap targets); the same `day_number` in the previous two plans (walking `parent_plan_id`) with prescribed vs logged reps and RPE; the questions/answers of her last 8 sessions (a backend copy of the consumer's shaping); her 40 latest `workout_comments`. It also returns the `facts` validation checks against.
- `prompts.py`: one suggestion per open exercise — `keep` (the default), `adjust` (1–6 sets, targets within min–max), `progress`/`regress` (to a listed option; default targets its min / max), `skip` (this workout only) — each with a reason and evidence (`client_answer`/`client_comment` quotes must be her exact words; `set_logs`, `rpe`, `joint_pain`, `profile`, `coach_note`, `progression_rule` state facts), plus an `overview` for the coach. Explains the progression engine so it only adds what the algorithm can't see.
- `validate.py` (pure): anything invalid (out-of-range targets, a non-edge swap, a foreign exercise, no reason, no surviving evidence — client quotes not found in her answers/comments are dropped) falls back to `keep` with the reason saying why; a no-op adjust becomes keep; locked (sets logged) and skipped exercises get no row; every open exercise gets exactly one.
- `dry_run.py`: `.venv/bin/python -m backend.coach_agent.dry_run --user-id <id>` (her next scheduled strength workout) or `--session-id N` prints the full prompt, raw response and validated suggestions without storing anything.

**`coach_suggestion_runs`** — one row per click: `id`, `session_id`, `user_id` (FKs, cascade), `overview`, `model`, `created_at`. **`exercise_suggestions`** — one row per exercise per run: `run_id` (FK, cascade), `session_exercise_id` (FK, cascade), `action` ∈ `keep, adjust, progress, regress, skip`, `proposed_sets`, `proposed_reps` (stored like `session_exercises.reps`), `proposed_exercise_id` (FK → `exercises`, set null), `before` jsonb (`{exercise_id, name, sets, reps}` when suggested), `reason`, `evidence` jsonb (`[{source, quote, session_id, verified}]`), `status` ∈ `pending, accepted, rejected, no_change, superseded` (a new run supersedes the session's pending ones), `decided_at`, `created_at`. `GET /api/admin/sessions/<id>/suggestions` returns the latest run. `POST /api/admin/exercise-suggestions/<id>/accept` re-checks (still pending, workout still scheduled, no sets logged, exercise unchanged since `before` — else 409) and applies it like the coach's own edit (`update_session_exercise_prescription`, with the swap for progress/regress, or `set_session_exercise_skipped`), so it becomes next week's baseline and restarts the two-week hold; `.../reject` marks it rejected.

### Admin client monitor

The PWA's `/admin` page has two tabs: **Onboard client** (profile → plan → review) and **Monitor clients**. The monitor reads through `backend/controllers/admin_monitor_controller.py` (both `X-Admin-Key`): `GET /api/admin/users` (every `user_profiles` row with `has_passkey`) and `GET /api/admin/users/<user_id>/monitor` (profile basics from `profile`, `user_joint_pain`, `user_period_logs` days, passkey count / last sign-in from `user_passkeys`, and `WorkoutPlanRepository.get_user_workout_history`: every session of every plan split into scheduled vs past, each with status/date (`workout_status`, shared with the dashboard), `is_period`, `has_feedback`, its `session_analysis` text + `audio_url`, duration, and exercises whose `rpe_logged` says whether effort was actually rated). Loading it never writes — unlike `get_unfinished_plan`, it doesn't close or progress plans. The one write is `PATCH /api/admin/session-exercises/<id>` (`{"sets": n, "reps": [one target per set], "note": "..."}`, reps or seconds, 1–10 sets, targets 1–600; `note` optional — the exercise's coach note, ≤ 500 chars, blank clears, left out keeps it; `exercise_id` optional — swaps the slot to another library exercise, also setting `rep_range` from its min/max, with the targets sent meant for the new exercise; the response then carries the new exercise's display fields as `exercise`. The PWA's editor picks it from the plan-builder library (`GET /api/admin/plan-builder`), same movement type listed first): the coach editing an exercise of a workout that is still **scheduled** and has none of that exercise's sets logged (else 409). It's stored the way progression writes `reps` (one number if all sets match, else a per-set list) and becomes the baseline next week's progression starts from — so an edit also restarts that exercise's two-week hold. The client's voice feedback is played through `GET /api/admin/sessions/<id>/feedback-audio` (signed URL, fetched when the coach presses play). Coach notes on the current week (`plans.coach_notes`, shown at the bottom of the client's dashboard) are edited with `PATCH /api/admin/users/<user_id>/coach-notes` (`{"coach_notes": "..."}`, blank clears, ≤ 2000 chars; 409 with no unfinished plan) and returned on the monitor as `current_plan`. Progression copies them into each next plan, so an edit carries forward. **Create progression** (`POST /api/admin/users/<user_id>/regenerate-plan`, `WorkoutPlanRepository.regenerate_current_plan`) deletes the client's current unfinished plan and re-runs `create_progressed_plan` from its `parent_plan_id`, keeping the same `scheduled_date`s — for after progression rules or inputs (e.g. RPE) changed. Refused (409, `PlanRegenerationError`) when there's no current plan, it has no parent (a first plan), or any of its sessions has `started_at`. The delete comes first (only one unfinished plan allowed), so a failure after it leaves no current plan until it's retried.

### Passkey authentication tables

Written by `AuthRepository` (`backend/repository/auth_repository.py`) via the passkey endpoints in `backend/controllers/auth_controller.py`; session cookies and route guards live in `backend/auth.py`. Enrollment is coach-issued: `POST /api/admin/users/<user_id>/enrollment-link` (requires `X-Admin-Key`) mints a one-time link; the user opens it in the PWA and creates a passkey. Session and enrollment tokens are stored only as SHA-256 hashes. All `user_id` FKs → `user_profiles.user_id` `ON DELETE CASCADE`, indexed.

**`user_passkeys`** — one row per registered passkey.

| Column | Type | Notes |
|---|---|---|
| `id` | int4 PK | `GENERATED BY DEFAULT AS IDENTITY` |
| `user_id` | text, FK | |
| `credential_id` | text, unique | base64url credential id — looked up on every sign-in |
| `public_key` | text | base64url COSE public key |
| `sign_count` | int8, default 0 | synced iCloud/Google passkeys always report 0 |
| `transports` | text[], nullable | as reported by the browser (e.g. `internal`, `hybrid`) |
| `aaguid` | text, nullable | authenticator model id |
| `backed_up` | bool, default `false` | whether the passkey is synced (backup state) |
| `created_at` / `last_used_at` | timestamptz | |

**`auth_challenges`** — pending WebAuthn challenges (5-minute expiry). Each `/verify` call reads the challenge back out of the credential's `clientDataJSON` and deletes the matching row in a single `DELETE`, so a challenge works at most once. Columns: `id`, `challenge` (text, unique, base64url), `purpose` (check ∈ `registration, authentication`), `user_id` (nullable — null for sign-in, since sign-in is username-less), `expires_at`, `created_at`. Expired rows are deleted opportunistically on each `POST /api/auth/login/options`.

**`auth_sessions`** — signed-in sessions behind the `fc_session` HttpOnly cookie (30-day expiry). Columns: `id`, `user_id`, `token_hash` (text, unique), `created_at`, `expires_at`, `last_seen_at` (bumped by `GET /api/auth/me`). Deleted on logout.

**`passkey_enrollment_tokens`** — coach-issued one-time sign-up links (48-hour expiry). Columns: `id`, `user_id`, `token_hash` (text, unique), `expires_at`, `used_at` (nullable — set once by a conditional `UPDATE` when enrollment succeeds), `created_at`. Minting a new link deletes that user's older unused ones.

### Notes on FK delete behavior

`movement_type_id` and `equipment_id` on `exercises`, `exercise_id` on `session_exercises`, and `joint_id` on `user_joint_pain`, have no cascade, so deleting a referenced row is blocked while referenced. `user_id` on `plans`, `user_joint_pain`, and the four passkey-auth tables is `ON DELETE CASCADE` — deleting a `user_profiles` row cascades to that user's `plans`, `user_joint_pain`, passkeys, auth sessions, enrollment tokens and pending challenges; `plans` in turn cascades to `sessions` via `plan_id`, `sessions` to `session_exercises` and `session_analysis` via `session_id`, and `session_exercises` cascades further to `session_exercise_set_logs` and `session_exercise_rpe` via `session_exercise_id`. `sessions` also cascades to `session_cardio_logs`; deleting a `cardio_exercises` row only nulls `session_cardio_logs.cardio_exercise_id` (the copied name stays). So deleting a `user_profiles` row transitively deletes all of that user's data across every child table. The join/edge tables (`exercise_loaded_joints`, `exercise_relationships`) cascade on delete from `exercises`. `plans.parent_plan_id` (self-referential) is the one exception to the "no cascade blocks delete" rule: it's `ON DELETE SET NULL`, so deleting a parent plan merely nulls out its children's `parent_plan_id` rather than being blocked or cascading further. Indexes exist on all FK columns.
