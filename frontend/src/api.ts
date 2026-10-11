import type { Dashboard, DayCompleteSummary, SetLog } from './types'

class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

let onUnauthorized: (() => void) | null = null

// Registered by AppStateProvider so an expired/revoked session anywhere in
// the app drops the user back to the sign-in screen.
export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    ...init,
  })
  if (res.status === 401) onUnauthorized?.()
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
  if (res.status === 204) return undefined as T
  return res.json()
}

export function fetchDashboard(userId: string): Promise<Dashboard> {
  return request<Dashboard>(`/users/${encodeURIComponent(userId)}/dashboard`)
}

export function startDay(sessionId: number, dayNumber: number): Promise<unknown> {
  return request(`/sessions/${sessionId}/days/${dayNumber}/start`, { method: 'POST' })
}

export function logSet(
  sessionId: number,
  sessionExerciseId: number,
  setNumber: number,
  completedReps: number,
): Promise<SetLog> {
  return request(`/sessions/${sessionId}/exercises/${sessionExerciseId}/sets/${setNumber}`, {
    method: 'PATCH',
    body: JSON.stringify({ completed_reps: completedReps }),
  })
}

export function logRpe(
  sessionId: number,
  sessionExerciseId: number,
  rpe: number,
): Promise<{ rpe: number }> {
  return request(`/sessions/${sessionId}/exercises/${sessionExerciseId}/rpe`, {
    method: 'PATCH',
    body: JSON.stringify({ rpe }),
  })
}

export function completeDay(sessionId: number, dayNumber: number): Promise<DayCompleteSummary> {
  return request(`/sessions/${sessionId}/days/${dayNumber}/complete`, { method: 'POST' })
}

export { ApiError }
