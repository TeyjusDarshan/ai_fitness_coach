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
  completed_sets: boolean[]
}

export type DayStatus = 'rest' | 'completed' | 'next' | 'upcoming'

export interface DashboardDay {
  day_number: number
  day_label: string
  split_name: string
  is_rest_day: boolean
  status: DayStatus
  started_at: string | null
  completed_at: string | null
  primary: ExerciseEntry[]
  secondary: ExerciseEntry[]
}

export interface Dashboard {
  session_id: number
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
  day_number: number
  total_time_seconds: number
  exercises_completed: number
  total_exercises: number
  sets_completed: number
  total_sets: number
  plan_completed: boolean
}
