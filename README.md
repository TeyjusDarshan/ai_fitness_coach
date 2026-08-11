# AI Fitness Coach

Turns free-text client intake into a personalized weekly workout plan, then tracks that plan
day-by-day through a React PWA — set logging, RPE, rest timers, and week-over-week progression.

## How it fits together

```
raw text ──▶ preprocessor_agent ──▶ profile ──▶ workout_agent ──▶ plan ──▶ Supabase
 (intake)      (LLM, agents/)      (jsonb)      (LLM, agents/)  (jsonb)   (sessions, session_exercises, ...)
                                                                              │
                                                                              ▼
                                                        backend/app.py (Flask API)
                                                                              │
                                                                              ▼
                                                          frontend/ (React + TS PWA)
```

Both agents are LangChain agents backed by Mistral. The workout agent's output follows a fixed
per-plan-type day skeleton (`DAY_TEMPLATES` in `agents/prompts_v1.py`) — the DB only stores the
per-exercise prescriptions, not the day structure, which is reconstructed from that skeleton at
read time.

## Project layout

| Path | What it is |
|---|---|
| `agents/` | LangChain agents: `preprocessor_agent.py` (raw text → structured profile), `workout_agent.py` (profile → weekly plan), prompt templates, tools |
| `backend/` | Flask API (`app.py`) + `repository/` — the Supabase access layer |
| `frontend/` | React + TypeScript PWA (Vite) — the app end users interact with |
| `workout_engine/` | Standalone FastAPI prototype UI for the profile → plan pipeline (separate from `backend/`/`frontend/`, not the production app) |
| `evaluation/` | Synthetic client `personas.py` for LLM-judging the intake → plan pipeline |
| `utilities/` | `workout_builder/` (exercise library CSVs + tooling) and `scripts/` (e.g. Supabase migration script) |
| `CLAUDE.md` | Full Supabase schema reference |

## Running it

**Backend** — requires `.env` with `SUPABASE_URL`, `SUPABASE_KEY`, `MISTRAL_API_KEY`:
```bash
python3 -m backend.app        # http://localhost:8001
```

**Frontend (dev)** — proxies `/api/*` to `:8001` (see `frontend/vite.config.ts`):
```bash
cd frontend && npm install && npm run dev   # http://localhost:5173
```

**Frontend (prod)**: `npm run build` in `frontend/`, then Flask serves the built `frontend/dist`
directly (see the catch-all route below) — no separate frontend server needed.

## API

All routes live in `backend/app.py`. Note the split: plan generation/completion is at the root
(`/workout-plan*`); everything else — the PWA's day-to-day tracking — is under `/api`.
There's no auth layer; `user_id` is a plain caller-supplied string (e.g. `"usr_10235"`).

| Method & path | Purpose |
|---|---|
| `POST /workout-plan` | Generate (or fetch the in-progress) plan for a user |
| `PATCH /workout-plan/<session_id>/complete` | Force-mark a session completed |
| `POST /api/users/<user_id>/progress-plan` | Generate the *next* week's plan from the last completed one |
| `GET /api/users/<user_id>/dashboard` | Weekly calendar view — day statuses for the PWA home screen |
| `POST /api/sessions/<id>/days/<n>/start` | Mark a day as started |
| `PATCH /api/sessions/<id>/exercises/<id>/sets/<n>` | Log reps for one completed set |
| `PATCH /api/sessions/<id>/exercises/<id>/rpe` | Log perceived exertion (1–10) for an exercise |
| `POST /api/sessions/<id>/days/<n>/complete` | Mark a day done; auto-completes the session on the last day |
| `GET /`, `GET /<path>` | Serves the built PWA (`frontend/dist`), falling back to `index.html` for client-side routes |

### Flow detail

**`POST /workout-plan`** — `{userid, raw_user_text}`
1. If the user already has an unfinished session, return it as-is (idempotent — no regeneration).
2. Otherwise: `raw_user_text` → `generate_user_profile` (preprocessor agent) → profile → `generate_workout_plan_v1` (workout agent) → plan.
3. Upsert `user_profiles`, insert `sessions` + `session_exercises` (retried once on transient failure).
4. Return the plan with `session_id` attached.

Errors: `400` missing fields · `502` profile extraction failed · `500` plan generation or persistence failure.

**`PATCH /workout-plan/<session_id>/complete`**
Directly flips `sessions.completed = true`. A manual/administrative shortcut — the PWA's real
completion path is the per-day `.../complete` route below, which completes the session
automatically once every day is done. `404` if the session doesn't exist.

**`POST /api/users/<user_id>/progress-plan`**
1. If an unfinished session already exists, return it (idempotent).
2. Else look up the user's last *completed* session — `404` if there isn't one.
3. Clone/advance it into a new session (`create_progressed_session`) and return the new plan.

Per-exercise rep targets and exercise selection for the new session are computed by the
autoregulation algorithm — see [Exercise progression](#exercise-progression) below.

**`GET /api/users/<user_id>/dashboard`**
1. Look up the user's unfinished session — `404` (`"No plan found for this user."`) if none.
2. Walk `DAY_TEMPLATES[plan_type].schedule`, tagging each day `rest` / `completed` / `next` /
   `upcoming` from `session_day_logs`.
3. Attach `session_duration_minutes` from the user's profile.

This is what `DashboardScreen` loads on login and on every visit to `/`.

**`POST /api/sessions/<id>/days/<n>/start`**
Upserts `session_day_logs.started_at` — set once on first entry into a day, never overwritten by
re-entry.

**`PATCH /api/sessions/<id>/exercises/<id>/sets/<n>`** — `{completed_reps}`
Upserts a `session_exercise_set_logs` row for that set (one row per set, idempotent per
`set_number`). Called on every set confirm in `ExerciseScreen`.

**`PATCH /api/sessions/<id>/exercises/<id>/rpe`** — `{rpe: 1-10}`
Upserts `session_exercise_rpe` (one row per exercise). Fired by the effort slider on change, and
defaulted to Medium (8) automatically if the user never touches it before moving to the next
exercise.

**`POST /api/sessions/<id>/days/<n>/complete`**
1. Sets `session_day_logs.completed_at` and computes summary stats (time, exercises/sets
   completed vs. total).
2. If every non-rest day in the plan template now has `completed_at`, also marks the whole
   `sessions` row completed and returns `plan_completed: true`.

Powers `SummaryScreen`; `plan_completed` triggers the "You've completed your whole plan!" message.

## Exercise progression

When `POST /api/users/<user_id>/progress-plan` builds the next session, it doesn't re-run the
workout agent — it carries forward the *same* exercise slots from the last completed session
(same `day_number`/`category`/`slot_label`/`sets`/`note`) and recalculates each slot's `reps`
autoregulated off how that exercise actually went. This is entirely deterministic code
(`_compute_progressed_reps` + `create_progressed_session` in `backend/repository/workout_plan_repository.py`) —
no LLM call is involved. Runs once per exercise slot, independently.

### Step 1 — did they hit the target?

An exercise slot "met its goal" only if *every* prescribed set was logged, each with
`completed_reps >= reps` (the target logged when the plan was made):

- **Met** → `actual_rpe` = whatever the user logged via `PATCH .../rpe` for that exercise
  (defaults to `10` if met but RPE was never logged).
- **Not met** (missing sets, or any set under target) → `actual_rpe` is forced to `10` regardless
  of what RPE was logged — a missed goal is always treated as maximally hard.

### Step 2 — turn effort into a volume multiplier

```
performance_factor = 8 (target RPE) − actual_rpe
```

| Effort logged | RPE | performance_factor | multiplier |
|---|---|---|---|
| Easy | 6 | +2 | **1.10** (increase load) |
| Medium (default) | 8 | 0 | **1.02** (hold steady) |
| Hard, *or* goal not met | 10 | −2 | **0.90** (deload) |

(A directly-posted RPE outside `{6, 8, 10}` — the API accepts 1–10 — snaps to whichever of these
three rows is numerically closest.)

### Step 3 — compute next session's reps

```
next_reps = round(multiplier × (total_reps_logged_last_time / 3))
```

floored at 1 rep. `total_reps_logged_last_time` is the sum of `completed_reps` across all logged
sets for that slot (so 3×10 logged = 30 → divided by 3 = a 10/set baseline before the multiplier).

*Example*: prescribed 3×10, all 3 sets logged at 10 reps.
- Logged "Easy" (RPE 6) → `round(1.10 × 30/3)` = **11 reps** next time.
- Logged "Medium" (RPE 8) → `round(1.02 × 30/3)` = **10 reps** — essentially unchanged.
- Logged "Hard" (RPE 10), or only 2 of 3 sets completed → `round(0.90 × 30/3)` = **9 reps**.

### Step 4 — swap exercises if the new target falls outside range

Every exercise in `exercises` has its own `min_reps`/`max_reps`. `next_reps` is checked against
the **current** exercise's bounds:

- **Below `min_reps`** → look up that exercise's `progression` edge in `exercise_relationships`
  whose `reason` contains "lack of strength" (an exercise-specific *regression*, not just any
  progression edge reversed). If one exists, the slot swaps to that exercise and `reps` is set to
  **the new exercise's own `min_reps`** (not the computed value). `rep_range` is refreshed to the
  new exercise's `min_reps-max_reps`. If no such edge exists, the exercise stays as-is and `reps`
  is just clamped up to its own `min_reps`.
- **Above `max_reps`** → same idea using the `progression` edge instead: swap to the harder
  variant and set `reps` to *that* exercise's `min_reps` (starting light on the new, harder
  movement rather than carrying the inflated number over). Falls back to clamping at `max_reps`
  if there's no progression edge.
- **Within bounds** → exercise unchanged, `reps` = the computed value from Step 3.

`sets`, `day_number`, `category`, `slot_label`, and `note` are always carried over unchanged,
whether or not the exercise itself was swapped.

## Data layer

See `CLAUDE.md` for the full Supabase schema (tables, FKs, cascade behavior) and the current
RLS status.
