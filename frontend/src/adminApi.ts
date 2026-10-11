import { ApiError } from './api'

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
  avoid_if: string
}

export interface PlanBuilderOptions {
  templates: Record<string, PlanTemplate>
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

export function generateProfile(adminKey: string, userId: string, rawUserText: string): Promise<ProfileResult> {
  return adminRequest(adminKey, '/admin/users/profile', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, raw_user_text: rawUserText }),
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
