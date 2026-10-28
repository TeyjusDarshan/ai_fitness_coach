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

// `isPeriod` is only sent when the user answered the "on your period?" prompt;
// the server applies it on the session's first start only.
export function startSession(sessionId: number, isPeriod?: boolean): Promise<unknown> {
  return request(`/sessions/${sessionId}/start`, {
    method: 'POST',
    body: isPeriod === undefined ? undefined : JSON.stringify({ is_period: isPeriod }),
  })
}

// Multipart, so the JSON Content-Type header is dropped and the browser sets
// the boundary itself.
export function uploadFeedbackAudio(sessionId: number, recording: Blob): Promise<{ feedback_audio_path: string }> {
  const form = new FormData()
  form.append('audio', recording, 'feedback')
  return request(`/sessions/${sessionId}/feedback-audio`, { method: 'POST', body: form, headers: {} })
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

export function completeSession(sessionId: number): Promise<DayCompleteSummary> {
  return request(`/sessions/${sessionId}/complete`, { method: 'POST' })
}

export { ApiError }
