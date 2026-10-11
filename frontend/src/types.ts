export interface SetLog {
  set_number: number
  completed_reps: number
}

export interface ExerciseEntry {
  id: number
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

export type DayStatus = 'rest' | 'completed' | 'next' | 'upcoming'

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
