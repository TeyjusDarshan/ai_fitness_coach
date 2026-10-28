import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { startSession } from '../api'
import { firstIncompleteIndex, flattenExercises } from '../utils'
import type { DashboardWorkout } from '../types'
import { useAppState } from './AppStateContext'

// Starts (or resumes) a workout from its dashboard panel or detail screen.
// The workout flow screens address the day by day_number, so this hands
// over to the current plan's matching `days` entry.
//
// Women are asked "are you on your period?" before a fresh start: `start`
// then parks the workout in `periodPrompt` for the screen to render with
// <PeriodPrompt>, and `answer` carries on. The server scales that session's
// reps down when the answer is yes.
export function useStartWorkout() {
  const { dashboard, gender, refreshDashboard } = useAppState()
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const [asking, setAsking] = useState<DashboardWorkout | null>(null)

  async function begin(workout: DashboardWorkout, isPeriod?: boolean) {
    const day = dashboard?.days.find((d) => d.session_id === workout.session_id)
    if (!day) return
    setError(null)
    try {
      await startSession(workout.session_id, isPeriod)
      // Reps (and possibly exercises) were rewritten server-side.
      if (isPeriod) await refreshDashboard()
    } catch (e) {
      // e.g. 409 when the day's scheduled date hasn't arrived in the app's
      // timezone yet, even though the device clock says it has.
      setError(e instanceof Error ? e.message : 'Could not start this workout.')
      return
    }
    // A fresh session opens with the warm-up video, whose "Start workout"
    // button leads to the first exercise. Resuming one that already has
    // logged sets skips straight back to where the user left off.
    const resuming = flattenExercises(day).some((ex) => ex.set_logs.length > 0)
    navigate(
      resuming
        ? `/day/${day.day_number}/exercise/${firstIncompleteIndex(day)}`
        : `/day/${day.day_number}/warmup`,
    )
  }

  async function start(workout: DashboardWorkout) {
    if (gender === 'female' && !workout.started_at) {
      setAsking(workout)
      return
    }
    await begin(workout)
  }

  const periodPrompt = {
    open: asking !== null,
    onAnswer: (isPeriod: boolean) => {
      const workout = asking
      setAsking(null)
      if (workout) void begin(workout, isPeriod)
    },
    onCancel: () => setAsking(null),
  }

  return { start, error, periodPrompt }
}
