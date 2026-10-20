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
  sets: number | null
  reps: string | null
  rep_range: string | null
  equipment: string[]
  note: string | null
  video_url: string | null
  set_logs: SetLog[]
  rpe: number | null
}

// 'missed': a training day whose date passed without it being completed —
// it can't be started any more, and its exercises repeat next week.
export type DayStatus = 'rest' | 'completed' | 'missed' | 'next' | 'upcoming'

export interface DashboardDay {
  day_number: number
  day_label: string
  split_name: string
  is_rest_day: boolean
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
  status: WorkoutStatus
  // YYYY-MM-DD in the app's timezone: the completion date for a completed
  // workout, otherwise its scheduled date.
  date: string
  scheduled_date: string
  started_at: string | null
  completed_at: string | null
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
}

export interface DayCompleteSummary {
  session_id: number
  day_number: number
  total_time_seconds: number
  exercises_completed: number
  total_exercises: number
  sets_completed: number
  total_sets: number
  plan_completed: boolean
}
