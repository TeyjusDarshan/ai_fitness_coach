# Handle missed workout days (no cron)

## Context
Right now an unfinished day never expires. The dashboard keeps Start on the first incomplete day (`app.py:186`, `DayRow.tsx:26`), and a plan only closes and auto-progresses once **every** session has `completed_at` (`workout_plan_repository.py:784`). One skipped day leaves the user stuck on that plan.

Decisions (confirmed with you):
- **Strict cutoff.** A workout not completed by the end of its `scheduled_date` (in `APP_TIMEZONE`) is **missed** and can't be done anymore.
- **Partial counts as missed.** A workout that was started with some sets logged but never completed is missed too.
- **Missed exercises carry forward unchanged.** Same exercise and same reps next week, with no RPE-based regression. The joint-pain multiplier still applies.
- **No cron job.** Missed is worked out from the date, and a plan whose workouts are all done or missed is closed the next time the app loads it.

## The rule
A session is **missed** when `completed_at IS NULL` and `scheduled_date < app_today()`. Nothing is stored: there's no new column and no migration. The rule is derived everywhere it's needed.

## Changes

### 1. Repository: `backend/repository/workout_plan_repository.py`
- **`is_session_missed(session, today)`**, a module-level helper for the rule above. Used by the API check, the dashboard, the plan close and progression.
- **Lazy close in `get_unfinished_plan`.** This is the one place every caller already goes through: dashboard (`app.py:162`), `/workout-plan` (`app.py:96`), progress-plan (`app.py:139`), admin initial-plan (`admin_plan_controller.py:48`). After loading the plan, if every session is completed or missed, call `mark_plan_completed`, which auto-progresses, then load again and return the new plan. It runs at most once, because the new plan's dates are never in the past (see below).
- **`mark_plan_completed`**: make it conditional (`.eq("completed", False)`) and only `_auto_progress` when a row actually came back. Two requests at once (two tabs, or the dashboard while the last workout completes) would otherwise create two plans.
- **`complete_session`**: its `still_open` query (`.is_("completed_at", "null")`) should also ignore sessions dated before today, since those are missed. Then if Monday was missed and the user finishes the last day, the plan closes immediately.
- **Progression**
  - `_flatten_session_exercises` tags each row with `missed` = session has no `completed_at`. By the time a plan is closed, every session without `completed_at` is a missed one. `PROGRESSION_SESSIONS_SELECT` gains `completed_at`.
  - In `_compute_progressed_reps`: if the row is `missed` and `injury_multiplier` isn't < 1.0, return `target_reps` unchanged (skip the `PROGRESSION_FALLBACK_RPE` path). An injury still goes down the hard path. Unchanged reps never trigger the min/max swap, so the exercise carries forward as-is.
- **New-plan dates** in `create_progressed_plan`: `new_start = max(source_day1 + PROGRESSION_SCHEDULE_OFFSET, app_today())`, then `scheduled_date_for(new_start, day_number)`. Weeks that close on time keep their weekday. A user returning after a long absence starts fresh today instead of getting a week that's already missed.

### 2. API: `backend/app.py`
- **`_deny_unless_session_open`**: after the future-date check, return 409 `{"error": "This workout was missed.", "missed": true}` when `is_session_missed(...)`. This blocks start, set, RPE and complete. A session that's already completed is still allowed.
- **`get_dashboard`**: a missed training day gets `status: "missed"`, and `next` goes to the first day that's neither completed nor missed. Miss Monday, and on Tuesday you see Monday: Missed, Tuesday: Start.

### 3. Frontend
- `frontend/src/types.ts`: add `'missed'` to `DayStatus`.
- `frontend/src/components/DayRow.tsx`: show a "Missed" label for `status === 'missed'`, plus a `day-row--missed` style.
- If midnight passes mid-workout, the next set/RPE/complete call gets a 409. Make sure the exercise screens show the error, as `DashboardScreen` already does.

### 4. Workout analysis: `workout_analysis_consumer/repository.py`
- `_fetch_previous_session_context`: if the parent plan's same-day session has no `completed_at` (missed), follow `parent_plan_id` back to the most recent same-day session that was completed (maximum a few hops). Otherwise the summary compares against an empty workout.

### 5. Docs: `CLAUDE.md`
- In the `sessions` section, replace "once the date arrives it stays open, so a missed day can be done late" with the strict missed rule and the lazy plan close. Note the missed-day carry-forward in the `plans`/progression description.

## Not needed (compared with the cron version)
No cron job, `CRON_SECRET`, `vercel.json` change, `missed_at` column or two-missed-weeks pause rule. A user who never opens the app never gets empty plans generated.

## Known trade-off
A coach only sees a stale week closed once the user (or the admin flow) loads it. Before that, any coach view of sessions should use `is_session_missed`.

## Flow after the change (4-day plan starting Monday)
| When | What happens |
|---|---|
| Mon | User skips the workout. |
| Tue | User opens the app. Dashboard: Mon **Missed**, Tue **Start**. |
| Tue–Fri | User does the remaining workouts. After Friday's, the week closes at once (3 done + 1 missed) and next week's plan is created. |
| Next week | The completed days progress as usual. Monday repeats last Monday's exercises and reps. |
| Alt: skips Fri too | The week closes the next time the app loads after Friday, e.g. Saturday. |
| Alt: gone 3 weeks | On return, the old week closes and the new week starts that day. |

## Verification
- **Unit tests** (`backend/tests/repository/workout_plan_repository_test.py`, `backend/tests/app_test.py`):
  - `is_session_missed` edge cases: today, yesterday, completed, partial.
  - A missed row keeps its reps and exercise. A missed row with joint pain drops by 1.
  - `get_unfinished_plan` closes and progresses a fully resolved plan and returns the new one, and leaves alone a plan with a future session.
  - A conditional `mark_plan_completed` doesn't progress twice.
  - New plan start is clamped to today.
  - `complete_session` closes the plan when the other sessions are missed.
  - `_deny_unless_session_open` returns 409 for a past, uncompleted session and 200 for a completed one.
  - Dashboard puts `next` after a missed day.
- Run `pytest`.
- **End to end (local):** use the admin flow to create a plan starting a few days ago and complete only one past session. Open the dashboard and check that the missed days show Missed and Start is on today's day. Backdate the remaining sessions via `execute_sql`, reload the dashboard, and confirm the old plan is `completed` and the new plan's missed-day `session_exercises.reps` equals the source's.
