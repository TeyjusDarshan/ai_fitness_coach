import { ApiError } from './api'
import type { CardioPlan, ExerciseEntry, WorkoutKind } from './types'

// Coach-only endpoints, authorized by the X-Admin-Key header rather than the
// passkey session cookie. Deliberately separate from api.ts's request(): a
// 401 here means a wrong admin key, not an expired sign-in, so it must not
// trigger the signed-out redirect.

export type Category = 'primary' | 'secondary'

export interface SlotTemplate {
  slot: string
  movement_type: string
  dominant: boolean
  orientation: string | null
}

export interface DayTemplate {
  day_number: number
  day_label: string
  split_name: string
  is_rest_day: boolean
  primary: SlotTemplate[]
  secondary: SlotTemplate[]
}

export interface PlanTemplate {
  plan_type: string
  label: string
  schedule: DayTemplate[]
}

export interface LibraryExercise {
  id: number
  name: string
  movement_type: string
  orientation: string
  dominant: boolean
  equipment: string[]
  loaded_joints: string[]
  min_reps: number | null
  max_reps: number | null
  // A hold measured in seconds, so min/max_reps are seconds.
  is_time_based: boolean
  avoid_if: string
}

export interface PlanBuilderOptions {
  templates: Record<string, PlanTemplate>
  // Per plan type, the rest days that become cardio days.
  cardio_days?: Record<string, number[]>
  exercises: LibraryExercise[]
}

// The preprocessor's output (see agents/mock_data_v1.py). Every field is
// LLM-extracted, so the UI treats all of it as optional.
export interface ClientProfile {
  user_id: string
  demographics?: { age?: number | null; sex?: string | null; height_cm?: number | null; weight_kg?: number | null }
  goals?: { primary_goal?: string | null; secondary_goals?: string[] | null }
  experience?: { training_experience_level?: string | null; current_activity_level?: string | null }
  health?: {
    medical_clearance_obtained?: boolean | null
    conditions?: { name?: string; location?: string; severity?: string; notes?: string }[] | null
    past_injuries?: { type?: string; side?: string; status?: string }[] | null
    pain_flags?: string[] | null
    movements_to_avoid?: string[] | null
  }
  availability?: { days_per_week?: number | null; session_duration_minutes?: number | null }
  equipment_access?: { available_equipment?: string[] | null }
  [key: string]: unknown
}

export interface ProfileResult {
  user_id: string
  name: string
  gender?: string | null
  profile: ClientProfile
  user_created: boolean
}

export interface PlanEntry {
  exercise_id: number
  sets: number
  reps: number
  note: string | null
}

export interface InitialPlanRequest {
  plan_type: string
  // YYYY-MM-DD: day 1's scheduled date; day N is scheduled N-1 days later.
  start_date: string
  coach_notes: string | null
  days: { day_number: number; primary: PlanEntry[]; secondary: PlanEntry[] }[]
}

export interface InitialPlanResult {
  user_id: string
  plan_id: number
  enrollment: { url: string; expires_at: string } | null
}

const ADMIN_KEY_STORAGE = 'fc_admin_key'

export function readStoredAdminKey(): string {
  try {
    return sessionStorage.getItem(ADMIN_KEY_STORAGE) ?? ''
  } catch {
    return ''
  }
}

export function storeAdminKey(key: string | null) {
  try {
    if (key) sessionStorage.setItem(ADMIN_KEY_STORAGE, key)
    else sessionStorage.removeItem(ADMIN_KEY_STORAGE)
  } catch {
    // storage unavailable (private mode); the key just isn't remembered
  }
}

async function adminRequest<T>(adminKey: string, path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey },
  })
  if (!res.ok) {
    let message = `Request failed (${res.status}).`
    try {
      const body = await res.json()
      message = body.error || message
    } catch {
      // non-JSON error body
    }
    throw new ApiError(res.status, message)
  }
  return res.json()
}

export function fetchPlanBuilderOptions(adminKey: string): Promise<PlanBuilderOptions> {
  return adminRequest(adminKey, '/admin/plan-builder')
}

export function generateProfile(
  adminKey: string,
  userId: string,
  name: string,
  gender: string,
  rawUserText: string,
): Promise<ProfileResult> {
  return adminRequest(adminKey, '/admin/users/profile', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, name, gender, raw_user_text: rawUserText }),
  })
}

export function createInitialPlan(
  adminKey: string,
  userId: string,
  plan: InitialPlanRequest,
): Promise<InitialPlanResult> {
  return adminRequest(adminKey, `/admin/users/${encodeURIComponent(userId)}/initial-plan`, {
    method: 'POST',
    body: JSON.stringify(plan),
  })
}

// ---------- client monitor ----------

export interface ClientSummary {
  user_id: string
  name: string | null
  gender: string | null
  updated_at: string | null
  has_passkey: boolean
}

export interface MonitorWorkout {
  session_id: number
  plan_id: number
  day_number: number
  name: string | null
  scheduled_date: string
  started_at: string | null
  completed_at: string | null
  status: 'completed' | 'missed' | 'scheduled'
  date: string
  is_period: boolean
  has_feedback: boolean
  duration_seconds: number | null
  analysis: string | null
  analysis_audio_url: string | null
  kind?: WorkoutKind
  // Set on a cardio workout: its level, rating and circuit.
  cardio?: CardioPlan
  exercises: ExerciseEntry[]
}

export interface ClientMonitor {
  client: {
    user_id: string
    name: string | null
    gender: string | null
    profile: {
      age: number | null
      sex: string | null
      primary_goal: string | null
      experience_level: string | null
      days_per_week: number | null
    }
    joint_pain: { joint: string; pain_level: string }[]
    period_days: string[]
    sign_in: { passkeys: number; last_used_at: string | null }
  }
  workouts: { scheduled: MonitorWorkout[]; past: MonitorWorkout[] }
  // The client's unfinished week, if any — where coach notes are edited.
  current_plan: { id: number; coach_notes: string | null } | null
}

export function fetchClients(adminKey: string): Promise<ClientSummary[]> {
  return adminRequest(adminKey, '/admin/users')
}

export function fetchClientMonitor(adminKey: string, userId: string): Promise<ClientMonitor> {
  return adminRequest(adminKey, `/admin/users/${encodeURIComponent(userId)}/monitor`)
}

// A short-lived link to the client's recorded voice feedback for a session.
export function fetchFeedbackAudioUrl(adminKey: string, sessionId: number): Promise<{ url: string }> {
  return adminRequest(adminKey, `/admin/sessions/${sessionId}/feedback-audio`)
}

// Replace the coach notes on the client's current week (blank clears them).
export function saveCoachNotes(
  adminKey: string,
  userId: string,
  coachNotes: string,
): Promise<{ id: number; coach_notes: string | null }> {
  return adminRequest(adminKey, `/admin/users/${encodeURIComponent(userId)}/coach-notes`, {
    method: 'PATCH',
    body: JSON.stringify({ coach_notes: coachNotes }),
  })
}

// Delete the client's current week and progress it again from the previous
// one, on the same dates. Refused (409) once a workout in it was started.
export function regeneratePlan(adminKey: string, userId: string): Promise<{ plan_id: number }> {
  return adminRequest(adminKey, `/admin/users/${encodeURIComponent(userId)}/regenerate-plan`, {
    method: 'POST',
  })
}

// The fields of an exercise entry that change when the coach swaps it.
export type SwappedExercise = Pick<
  ExerciseEntry,
  'exercise_id' | 'name' | 'movement_type' | 'orientation' | 'dominant' | 'is_time_based' | 'equipment' | 'video_url' | 'rep_range'
>

// Change an upcoming workout's sets, per-set targets (reps, or seconds for a
// timed exercise) and coach note (blank clears it) for one exercise, and
// optionally swap it for another library exercise (`exerciseId`; the targets
// are then for the new one). Returns the stored values, plus the new
// exercise's display fields when it was swapped.
export function editPrescription(
  adminKey: string,
  sessionExerciseId: number,
  sets: number,
  reps: number[],
  note: string,
  exerciseId?: number,
): Promise<{ id: number; sets: number; reps: string; note: string | null; exercise?: SwappedExercise }> {
  return adminRequest(adminKey, `/admin/session-exercises/${sessionExerciseId}`, {
    method: 'PATCH',
    body: JSON.stringify({ sets, reps, note, exercise_id: exerciseId }),
  })
}

// A short-lived link to the client's voice note on one exercise of a session.
export function fetchExerciseFeedbackAudioUrl(adminKey: string, sessionExerciseId: number): Promise<{ url: string }> {
  return adminRequest(adminKey, `/admin/session-exercises/${sessionExerciseId}/feedback-audio`)
}

// ---------- AI Coach suggestions ----------

export type SuggestionAction = 'keep' | 'adjust' | 'progress' | 'regress' | 'skip'
export type SuggestionStatus = 'pending' | 'accepted' | 'rejected' | 'no_change' | 'superseded'

export interface SuggestionEvidence {
  source: string
  quote: string
  session_id: number | null
  // A quote checked against her own answers/comments (data evidence isn't).
  verified: boolean
}

export interface SuggestionPrescription {
  exercise_id: number
  name: string
  sets: number | null
  reps: string | null
  rep_range: string | null
  is_time_based: boolean
}

export interface ExerciseSuggestion {
  id: number
  session_exercise_id: number
  action: SuggestionAction
  status: SuggestionStatus
  reason: string
  evidence: SuggestionEvidence[]
  current: SuggestionPrescription
  // Null for keep and skip.
  proposed: SuggestionPrescription | null
}

export interface SuggestionRun {
  run: { id: number; overview: string | null; model: string | null; created_at: string | null } | null
  suggestions: ExerciseSuggestion[]
}

// What changed on the exercise when a suggestion was accepted.
export interface AppliedExerciseChange {
  id: number
  sets?: number
  reps?: string
  skipped?: boolean
  skip_reason?: string | null
  exercise?: SwappedExercise
}

// The latest AI Coach suggestions for a workout (run is null if never asked).
export function fetchSuggestions(adminKey: string, sessionId: number): Promise<SuggestionRun> {
  return adminRequest(adminKey, `/admin/sessions/${sessionId}/suggestions`)
}

// Ask the AI Coach to review an upcoming workout (takes up to a minute).
export function requestSuggestions(adminKey: string, sessionId: number): Promise<SuggestionRun> {
  return adminRequest(adminKey, `/admin/sessions/${sessionId}/suggestions`, { method: 'POST' })
}

export function acceptSuggestion(
  adminKey: string,
  suggestionId: number,
): Promise<{ id: number; status: 'accepted'; exercise: AppliedExerciseChange }> {
  return adminRequest(adminKey, `/admin/exercise-suggestions/${suggestionId}/accept`, { method: 'POST' })
}

export function rejectSuggestion(adminKey: string, suggestionId: number): Promise<{ id: number; status: 'rejected' }> {
  return adminRequest(adminKey, `/admin/exercise-suggestions/${suggestionId}/reject`, { method: 'POST' })
}

// Bring back an exercise skipped for an upcoming workout.
export function restoreSkippedExercise(
  adminKey: string,
  sessionExerciseId: number,
): Promise<{ id: number; skipped: false; skip_reason: null }> {
  return adminRequest(adminKey, `/admin/session-exercises/${sessionExerciseId}`, {
    method: 'PATCH',
    body: JSON.stringify({ skipped: false }),
  })
}
