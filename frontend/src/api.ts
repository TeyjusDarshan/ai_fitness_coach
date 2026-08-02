import type { Dashboard, DayCompleteSummary } from './types'

class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
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

export function fetchDashboard(userId: string): Promise<Dashboard> {
  return request<Dashboard>(`/users/${encodeURIComponent(userId)}/dashboard`)
}

export function startDay(sessionId: number, dayNumber: number): Promise<unknown> {
  return request(`/sessions/${sessionId}/days/${dayNumber}/start`, { method: 'POST' })
}

export function toggleSet(
  sessionId: number,
  sessionExerciseId: number,
  setIndex: number,
  completed: boolean,
): Promise<{ completed_sets: boolean[] }> {
  return request(`/sessions/${sessionId}/exercises/${sessionExerciseId}/sets/${setIndex}`, {
    method: 'PATCH',
    body: JSON.stringify({ completed }),
  })
}

export function completeDay(sessionId: number, dayNumber: number): Promise<DayCompleteSummary> {
  return request(`/sessions/${sessionId}/days/${dayNumber}/complete`, { method: 'POST' })
}

export { ApiError }
