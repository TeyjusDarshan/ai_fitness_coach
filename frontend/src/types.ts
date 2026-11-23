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

// --- Food (voice diet tracking) -------------------------------------------

export type MealName = 'breakfast' | 'lunch' | 'dinner' | 'snack'
// Why a meal log couldn't be worked out.
export type MealLogError = 'no_speech' | 'no_food' | 'failed' | 'timeout'

// One ingredient of a logged dish, with the amount assumed for her portion.
export interface MealIngredient {
  ingredient_id: number
  name: string
  grams: number
  // What was estimated before she changed it.
  default_grams: number
  edited: boolean
  // Shown in this unit (teaspoon, piece…) instead of grams when set.
  display_unit: string | null
  grams_per_display_unit: number | null
}

// One dish she said she ate.
export interface MealItem {
  id: number
  name: string
  // The dish name in Tamil script (null on older entries): what she sees.
  name_ta: string | null
  meal: MealName | null
  quantity: number
  unit: string
  grams: number | null
  // She gave no amount, so one usual serving was assumed.
  assumed: boolean
  // A dish that couldn't be worked out yet (no nutrients).
  needs_review: boolean
  edited: boolean
  protein_g: number
  fibre_g: number
  energy_kcal: number
  ingredients?: MealIngredient[]
}

export interface MealItemDetail extends MealItem {
  ingredients: MealIngredient[]
  meal_log_id: number
  logged_for: string
}

// One recording and what was heard in it.
export interface MealLog {
  id: number
  logged_for: string
  status: 'processing' | 'ready' | 'confirmed' | 'failed'
  error: MealLogError | null
  created_at: string
  // Meals she said she didn't eat ("breakfast skip pannitten"): no dishes.
  skipped_meals?: MealName[]
  items: MealItem[]
}

// Calories and the four goal nutrients, for a day's totals or her targets.
export interface DietGoals {
  energy_kcal: number
  protein_g: number
  fibre_g: number
  carbs_g: number
  fat_g: number
}

// Her view of a day: the goal nutrients against her targets, and the day's logs.
export interface DietDay {
  date: string
  totals: DietGoals
  targets: DietGoals
  logs: MealLog[]
}

// One of her recent days, for the Past days list.
export interface DietDaySummary {
  date: string
  totals: DietGoals
  // Dishes logged (in worked-out logs) that day.
  dishes: number
}

export interface RecentDiet {
  targets: DietGoals
  // Newest first, including days with nothing logged.
  days: DietDaySummary[]
}

// --- Diet setup (once, when she first opens Diet) ---------------------------

export type DietGoal = 'lose' | 'maintain' | 'gain'
export type BmiCategory = 'underweight' | 'healthy' | 'overweight'

export interface DietSetupInput {
  height_cm: number
  weight_kg: number
  age: number
}

// The target weights she may pick for losing or gaining, and ours.
export interface TargetWeightRange {
  min: number
  max: number
  suggested: number
}

// Her BMI and the goal we recommend; `allowed_goals` leaves out losing
// weight when she is underweight and gaining when she is overweight.
export interface DietSetupAssessment {
  bmi: number
  bmi_category: BmiCategory
  recommended_goal: DietGoal
  allowed_goals: DietGoal[]
  target_weights: Partial<Record<'lose' | 'gain', TargetWeightRange>>
  bmr: number
  tdee: number
}

export interface DietSetupResult extends DietSetupAssessment {
  goal: DietGoal
  // Calories above (+) or below (−) maintenance.
  adjustment_kcal: number
  // Losing or gaining: her target and the healthy pace to it. `weeks` and
  // `target_date` are null when the calorie floors leave too little room
  // to promise a date.
  target_weight_kg: number | null
  weekly_change_kg: number | null
  weeks: number | null
  target_date: string | null
  targets: DietGoals
}
