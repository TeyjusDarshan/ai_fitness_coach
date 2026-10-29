# AI Fitness Coach

## Database Schema (Supabase)

Project: `khwrrvmejvrupokvfwvf` ("AI powered Fitness trainer", region `ap-northeast-1`, Postgres 17.6).

> ⚠️ **RLS is disabled on every table below.** All 19 tables are exposed to the `anon`/`authenticated` roles — anyone with the publishable key can read or write every row. This was originally tolerable while the data was public reference content (exercise library); that condition has now been **triggered**, not just theoretical — `user_profiles`, `plans`, `sessions`, `session_exercises`, `session_exercise_set_logs`, `session_exercise_rpe`, `user_joint_pain`, `user_period_logs`, and `session_analysis` hold real per-user data (generated profiles, weekly plans, scheduled workout days and their progress, prescribed exercises, per-set rep logs, RPE, reported joint pain, logged period days, generated LLM workout summaries) and are still exposed with no RLS. This is a known, accepted gap, not an oversight. Remediation SQL is available on request — don't apply it blind, since enabling RLS with no policies blocks all access.
>
> This includes the passkey-auth tables (`user_passkeys`, `auth_challenges`, `auth_sessions`, `passkey_enrollment_tokens`): the API-level passkey sign-in is only as strong as the secrecy of the publishable key, since anyone holding it can insert an `auth_sessions` row (or their own passkey) for any `user_id` and impersonate that user. Kept this way deliberately (decision 2026-09-27) because the backend's `SUPABASE_KEY` is the publishable key. The fix is to switch the backend (and `workout_analysis_consumer`) to the secret/service-role key, which bypasses RLS, and then enable RLS on these tables.

> The exercise-library schema (`movement_types`, `equipment`, `joints`, `exercises`, `exercise_loaded_joints`, `exercise_relationships`) is edited in the Workout Builder board (`utilities/workout_builder`, `.venv/bin/python utilities/workout_builder/app.py` → http://localhost:8765), which reads and writes these tables in Supabase directly — there is no CSV copy or migration step any more (the old `exercises.csv` / `relationships.csv` / `migrate_exercises_to_supabase.py` flow was removed; git history has them). The board saves its whole state on each change and the server writes only the differences; it refuses to delete an exercise that `session_exercises` still references (no-cascade FK) — take it off the board instead. It offers only `progression`/`regression` links, matching the table's check. Plan progression follows only one progression and one lack-of-strength regression edge per exercise, so avoid drawing more. Populated as of this writing: 66 exercises, 203 joint links, 108 relationships.

### Entity overview

`exercises` is the hub table. `movement_types`, `equipment`, and `joints` are lookup tables. `exercise_loaded_joints` is a many-to-many join between `exercises` and `joints`. `exercise_relationships` is a self-referential edge table (progression/regression links between exercises). `user_profiles` holds one generated profile per user; `user_joint_pain` holds one row per (user, joint) the user has reported pain for. Workouts form a three-level hierarchy: `plans` holds one row per weekly workout plan for a user; `sessions` holds one row per **training day** of a plan (its `day_number`, `scheduled_date`, and start/completion timestamps); `session_exercises` is a join table between `sessions` and `exercises` recording the prescribed sets/reps per exercise slot of that day. `session_exercise_set_logs` and `session_exercise_rpe` track per-set rep completion and per-exercise RPE against a `session_exercises` row; `session_analysis` holds one LLM-generated Tanglish summary per session, written by the standalone `workout_analysis_consumer` service (see below). The passkey-auth tables — `user_passkeys`, `auth_sessions`, `passkey_enrollment_tokens`, `auth_challenges` — hang off `user_profiles` (see "Passkey authentication tables" below).

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
| `is_time_based` | bool, default `false` | true for static holds measured in **seconds** rather than reps — currently Superman, Static split squat, standing wall plank, Knee plank, full plank, Side Plank, Dead-Bug. For these, `min_reps`/`max_reps` (and the sets' `reps` in `session_exercises`) are seconds. Set with the Workout Builder form's "Timed hold" checkbox. Returned on dashboard exercise entries; the PWA runs these with the timed flow (`TimedExerciseScreen`: countdown, hold timer, rest, difficulty) and logs seconds held as `completed_reps`. Progression steps them +5 s (correct) / +10 s (easy) / −5 s (hard) instead of ±1/2 reps (`TIMED_*_STEP`); the analysis consumer marks them `unit: seconds` |
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

One row per non-rest day of a plan's `DAY_TEMPLATES[plan_type]` schedule (rest days have no row). Created alongside the plan by `create_plan` / `create_progressed_plan`. Drives the PWA dashboard and the end-of-day summary screen's Total Time stat. `GET /api/users/<user_id>/dashboard` returns `workouts` — one panel per session: the last two past ones (completed or missed, reaching into the previous completed plan via `get_previous_plan_workouts` early in a new plan), then every scheduled one, each with `status` (completed / missed / scheduled), a display `date` (completion date in `APP_TIMEZONE`, else `scheduled_date`), `is_next`, `can_start` (scheduled for today) and its exercises with set logs and RPE, for the panel's View screen (`/workout/<session_id>`). It also still returns the per-day `days` list (rest / completed / missed / next / upcoming, plus `locked`) that the in-workout screens address by `day_number`.

| Column | Type | Notes |
|---|---|---|
| `id` | int4 PK | `GENERATED BY DEFAULT AS IDENTITY` — the id the PWA's `/api/sessions/<session_id>/…` routes and the WhatsApp share message ("Session ID: …") use |
| `plan_id` | int4, FK → `plans.id` | `ON DELETE CASCADE` |
| `day_number` | int2 | check 1–7, matches `DAY_TEMPLATES[plan_type].schedule[].day_number` |
| `scheduled_date` | date | the day this session opens. `create_plan`: coach-chosen start date + (`day_number` − 1); `create_progressed_plan`: the source plan's same-day session + 7 days, or — if that week would start in the past (the source plan closed late) — the plan starts today |
| `started_at` | timestamptz, nullable | set once, on the first `start_session` call — never overwritten by a later re-entry |
| `completed_at` | timestamptz, nullable | set when the session's summary screen is reached (`complete_session`) |
| `feedback_audio_path` | text, nullable | object path (`session_<id>.<ext>`) of the client's recorded voice feedback in the **private** `voice-feedback` Storage bucket, recorded on the PWA's end-of-day summary screen (`/day/:n/summary`, uploaded when she taps "Share Workout & Voice Note", behind an upload-progress screen, just before WhatsApp opens) via `POST /api/sessions/<id>/feedback-audio` (≤ 4 MB; a re-record overwrites). A path, not a URL: it's read through short-lived signed URLs — `GET /api/sessions/<id>/feedback-audio` (the owner) or `GET /api/admin/sessions/<id>/feedback-audio` (`X-Admin-Key`, for the coach). Bucket access for the publishable key comes from the `voice-feedback app access` policy on `storage.objects`. The analysis consumer also downloads it and transcribes it for the summary prompt (see `session_analysis`) |
| `is_period` | bool, default `false` | set by the first `start_session` when a female user answers "yes" to "are you on your period?" (`POST /api/sessions/<id>/start` with `{"is_period": true}`; ignored for anyone whose `user_profiles.gender` isn't `female`, and never re-applied on resume). On that first start `_apply_period_adjustment` rewrites the session's `session_exercises` rows **in place** to 70% of the planned reps (`PERIOD_REP_FACTOR`), swapping to the "lack of strength" regression — or clamping to `min_reps` when there's no edge — wherever that falls below an exercise's `min_reps`. The originals are not kept. Progression never learns from a period session: `_progression_sources` uses each day's latest non-period session (walking up `parent_plan_id`, at most `MAX_PROGRESSION_HOPS` plans) as the source and the non-period session before it for the two-week hold check; a day with no non-period history carries the period rows forward unchanged. The analysis consumer is told (`is_period`) and skips period sessions as `previous_session` |
| `created_at` | timestamptz, default `now()` | |

Unique: (`plan_id`, `day_number`). **Scheduled-date lock:** the backend refuses start / set / RPE / complete for a session (409, `_deny_unless_session_open` in `backend/app.py`) while `scheduled_date` is after today in `APP_TIMEZONE` (env, default `Asia/Kolkata`; see `app_today()`). **Missed days (strict):** a session with no `completed_at` whose `scheduled_date` is before today is *missed* (`is_session_missed`) — including one that was started with sets logged but never finished. Missed is derived, not stored (no column, no cron job): a missed session is refused the same way (409, `"missed": true`), shows as `missed` on the dashboard, and `next` moves past it. Once every session of a plan is completed or missed, the plan is closed via `mark_plan_completed` (which auto-progresses it) — either by `complete_session` when the last open session is finished, or lazily by `get_unfinished_plan` the next time anything loads the plan (dashboard, `/workout-plan`, progress-plan, admin), which then returns the new plan. `mark_plan_completed` only matches while `completed = false`, so racing closes progress a plan once. In progression, a missed session's exercises carry forward unchanged (same exercise, same reps) instead of taking the missing-RPE → hard path; reported joint pain still reduces them. Replaces the former `session_day_logs` table.

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

One row per `session_exercises` row, written via `WorkoutPlanRepository.log_rpe` — RPE is logged once per exercise (not per set).

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

One row per session that's been analyzed. Written by the standalone `workout_analysis_consumer` package (repo root, alongside `backend`/`frontend`) — a Kafka consumer, independent of the Flask app, that listens on the `workout-complete-events` topic. Those events are produced by `backend/kafka_producer` from the WhatsApp webhook (`backend/controllers/whatsapp_webhook_controller.py`) when the client shares a finished workout with the coach: the shared message carries a `Session ID: <sessions.id>` line, and the event payload is `{session_id, phone_number}`. On each event the consumer reads that session's `session_exercises` (with `session_exercise_set_logs` and `session_exercise_rpe` joined in), its plan, the user's `user_profiles.profile`, and their `user_joint_pain`. If the session has a `feedback_audio_path`, it downloads the recording and transcribes it with a Sarvam batch speech-to-text job (`stt/`, `saaras:v4`, `ta-IN`, `codemix`; `STT_JOB_TIMEOUT_SECONDS`, default 180) and passes the transcript as `client_voice_feedback`. This is best-effort: a failed transcription is logged and the summary is written without it. It then prompts Claude (`claude-sonnet-5-5`, via the `anthropic` SDK with server-side refusal fallback; a refusal raises `SummaryRefusedError` rather than saving anything) to write a short coach-style summary in **Tanglish** (Tamil-majority, code-switching into English for gym/fitness terms — see `workout_analysis_consumer/prompts.py`), and upserts the result here. If the plan has a `parent_plan_id`, the consumer also fetches the parent plan's session for the **same `day_number`** (its exercises, set logs, RPE and start/completion times) and includes it as `previous_session` context, so the prompt can call out individual- and exercise-specific progress compared to the client's last time on that day of their split (see `AnalysisRepository._fetch_previous_session_context`). If that session was missed, it walks further up `parent_plan_id` (up to `MAX_PREVIOUS_PLAN_HOPS` plans) to the most recent completed one. The voice note is stored as `plan_<plan_id>/day_<day_number>.ogg`.

| Column | Type | Notes |
|---|---|---|
| `id` | int4 PK | `GENERATED BY DEFAULT AS IDENTITY` |
| `session_id` | int4, FK → `sessions.id` | `ON DELETE CASCADE` |
| `analysis` | text | the generated Tanglish summary |
| `audio_url` | text, nullable | URL of the generated voice analysis (TTS audio) for `analysis` |
| `created_at` | timestamptz, default `now()` | |

Unique: (`session_id`) — makes the consumer's write an idempotent upsert, so redelivering an already-processed Kafka message overwrites rather than duplicates. (Was `session_day_analysis`, keyed by plan + day, before the plans/sessions split.)

### Admin client monitor

The PWA's `/admin` page has two tabs: **Onboard client** (profile → plan → review) and **Monitor clients**. The monitor reads through `backend/controllers/admin_monitor_controller.py` (both `X-Admin-Key`): `GET /api/admin/users` (every `user_profiles` row with `has_passkey`) and `GET /api/admin/users/<user_id>/monitor` (profile basics from `profile`, `user_joint_pain`, `user_period_logs` days, passkey count / last sign-in from `user_passkeys`, and `WorkoutPlanRepository.get_user_workout_history`: every session of every plan split into scheduled vs past, each with status/date (`workout_status`, shared with the dashboard), `is_period`, `has_feedback`, its `session_analysis` text + `audio_url`, duration, and exercises whose `rpe_logged` says whether effort was actually rated). Loading it never writes — unlike `get_unfinished_plan`, it doesn't close or progress plans. The one write is `PATCH /api/admin/session-exercises/<id>` (`{"sets": n, "reps": [one target per set]}`, reps or seconds, 1–10 sets, targets 1–600): the coach editing an exercise of a workout that is still **scheduled** and has none of that exercise's sets logged (else 409). It's stored the way progression writes `reps` (one number if all sets match, else a per-set list) and becomes the baseline next week's progression starts from — so an edit also restarts that exercise's two-week hold. The client's voice feedback is played through `GET /api/admin/sessions/<id>/feedback-audio` (signed URL, fetched when the coach presses play).

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

`movement_type_id` and `equipment_id` on `exercises`, `exercise_id` on `session_exercises`, and `joint_id` on `user_joint_pain`, have no cascade, so deleting a referenced row is blocked while referenced. `user_id` on `plans`, `user_joint_pain`, and the four passkey-auth tables is `ON DELETE CASCADE` — deleting a `user_profiles` row cascades to that user's `plans`, `user_joint_pain`, passkeys, auth sessions, enrollment tokens and pending challenges; `plans` in turn cascades to `sessions` via `plan_id`, `sessions` to `session_exercises` and `session_analysis` via `session_id`, and `session_exercises` cascades further to `session_exercise_set_logs` and `session_exercise_rpe` via `session_exercise_id`. So deleting a `user_profiles` row transitively deletes all of that user's data across every child table. The join/edge tables (`exercise_loaded_joints`, `exercise_relationships`) cascade on delete from `exercises`. `plans.parent_plan_id` (self-referential) is the one exception to the "no cascade blocks delete" rule: it's `ON DELETE SET NULL`, so deleting a parent plan merely nulls out its children's `parent_plan_id` rather than being blocked or cascading further. Indexes exist on all FK columns.
