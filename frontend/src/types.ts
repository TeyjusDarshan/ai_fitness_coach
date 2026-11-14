export interface SetLog {
  set_number: number
  completed_reps: number
}

export interface ExerciseEntry {
  id: number
  category: 'primary' | 'secondary'
  slot: string | null
  exercise_id: number
  name: string
  movement_type: string
  orientation: string | null
  dominant: boolean
  // A hold measured in seconds (e.g. a plank): `reps` and set logs are
  // seconds, and the workout runs it with TimedExerciseScreen.
  is_time_based: boolean
  sets: number | null
  reps: string | null
  rep_range: string | null
  equipment: string[]
  note: string | null
  video_url: string | null
  set_logs: SetLog[]
  rpe: number | null
  // Whether `rpe` was actually rated (the server reports an unrated one as 8).
  rpe_logged?: boolean
  // Whether she left a voice note on its feedback screen.
  has_feedback?: boolean
  // Skipped by the coach for this workout only (an accepted AI Coach
  // suggestion): not part of her workout run.
  skipped?: boolean
  skip_reason?: string | null
}

// A cardio day's ratings: they decide next week's cardio level.
export type CardioRating = 'easy' | 'medium' | 'hard'

export interface CardioExercise {
  id: number
  name: string
  // Public mp4 clip (720p, no audio) and its poster frame.
  video_url: string | null
  poster_url: string | null
}

// How one exercise of one round actually went (session_cardio_logs), with
// the rest that followed it — null rest fields after the final exercise or
// when she left before the rest ended. Seconds are active time; pauses are
// counted separately.
export interface CardioLogEntry {
  round: number
  position: number
  name: string
  planned_seconds: number
  actual_seconds: number | null
  paused_seconds: number | null
  skipped: boolean
  rest_planned_seconds: number | null
  rest_actual_seconds: number | null
  rest_paused_seconds: number | null
  rest_skipped: boolean
}

export interface CardioLogSummary {
  exercises_done: number
  exercises_skipped: number
  // Planned but never reached (she left early).
  exercises_missing: number
  rests_skipped: number
  active_seconds: number
  paused_seconds: number
}

// What a cardio session runs: the whole circuit, `rounds` times, each
// exercise for `work_seconds`, with rests between exercises and rounds.
export interface CardioPlan {
  rounds: number
  // What she actually does: 70% of planned_work_seconds on a period day.
  work_seconds: number
  planned_work_seconds: number
  is_period: boolean
  rating: CardioRating | null
  get_ready_seconds: number
  exercise_rest_seconds: number
  round_rest_seconds: number
  // How long the whole circuit takes, rests included.
  estimated_seconds: number
  exercises: CardioExercise[]
  // What she actually did, step by step (empty until she runs it).
  log: CardioLogEntry[]
  log_summary: CardioLogSummary
}

// 'strength' runs exercise by exercise with sets and reps; 'cardio' is a
// follow-along circuit (CardioScreen). Null on a rest day.
export type WorkoutKind = 'strength' | 'cardio'

// 'missed': a training day whose date passed without it being completed —
// it can't be started any more, and its exercises repeat next week.
export type DayStatus = 'rest' | 'completed' | 'missed' | 'next' | 'upcoming'

export interface DashboardDay {
  day_number: number
  day_label: string
  split_name: string
  is_rest_day: boolean
  kind: WorkoutKind | null
  // Set on a cardio day.
  cardio?: CardioPlan
  status: DayStatus
  // The sessions row for this training day (null on rest days).
  session_id: number | null
  // YYYY-MM-DD in the app's timezone: the session's scheduled_date, or for
  // a rest day, its place in the plan's week.
  date: string
  // Training day whose date hasn't arrived yet — it can't be started.
  locked: boolean
  started_at: string | null
  completed_at: string | null
  primary: ExerciseEntry[]
  secondary: ExerciseEntry[]
}

// A workout panel's status: 'missed' is a workout whose date passed without
// it being completed (or one left undone when its plan was closed).
export type WorkoutStatus = 'completed' | 'missed' | 'scheduled'

// One training day on the dashboard's workout list — the last two past
// workouts (possibly from the previous plan), then every scheduled one.
export interface DashboardWorkout {
  session_id: number
  plan_id: number
  day_number: number
  name: string
  kind: WorkoutKind
  // Set on a cardio workout.
  cardio?: CardioPlan
  status: WorkoutStatus
  // YYYY-MM-DD in the app's timezone: the completion date for a completed
  // workout, otherwise its scheduled date.
  date: string
  scheduled_date: string
  started_at: string | null
  completed_at: string | null
  // Completed today or scheduled for today — the dashboard's Today card.
  is_today: boolean
  // Time from start to finish, once completed.
  duration_seconds: number | null
  // The first scheduled workout.
  is_next: boolean
  // Scheduled for today — the only workout that can be started.
  can_start: boolean
  exercises: ExerciseEntry[]
}

export interface Dashboard {
  plan_id: number
  plan_type: string
  plan_selection_reason: string | null
  medical_clearance_warning: string | null
  coach_notes: string | null
  safety_summary: {
    excluded_movements?: string[]
    excluded_joints?: string[]
    excluded_equipment?: string[]
  } | null
  session_duration_minutes: number | null
  days: DashboardDay[]
  workouts: DashboardWorkout[]
  // Plant points: 25 per completed workout, across every plan.
  points: number
}

// One page of GET /users/<id>/past-workouts, plus the totals across every page.
export interface PastWorkoutsPage {
  workouts: DashboardWorkout[]
  total: number
  completed: number
  missed: number
}

export interface DayCompleteSummary {
  session_id: number
  day_number: number
  kind?: WorkoutKind
  // A cardio session's level and rating (for a cardio session,
  // exercises_completed / total_exercises count the circuit).
  rounds?: number
  work_seconds?: number
  rating?: CardioRating | null
  is_period?: boolean
  total_time_seconds: number
  exercises_completed: number
  total_exercises: number
  sets_completed: number
  total_sets: number
  plan_completed: boolean
  // Grow points after this workout, and how many it added (0 if it was
  // already completed before).
  points: number
  points_earned: number
}
