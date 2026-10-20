import { useEffect } from 'react'
import { HeroHeader } from '../components/HeroHeader'
import { WorkoutPanel } from '../components/WorkoutPanel'
import { useAppState } from '../state/AppStateContext'
import { useStartWorkout } from '../state/useStartWorkout'

export function DashboardScreen() {
  const { dashboard, loading, error, refreshDashboard, logout } = useAppState()
  const { start, error: startError } = useStartWorkout()

  useEffect(() => {
    refreshDashboard().catch(() => {
      // surfaced via `error`
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (loading && !dashboard) {
    return (
      <div className="screen">
        <div className="spinner" />
      </div>
    )
  }

  if (error && !dashboard) {
    return (
      <div className="screen">
        <div className="error-banner">{error}</div>
        <button className="btn-secondary" onClick={() => void logout()}>
          Sign out
        </button>
      </div>
    )
  }

  if (!dashboard) return null

  const timerLabel = dashboard.session_duration_minutes
    ? `${dashboard.session_duration_minutes} min`
    : null

  return (
    <div className="screen">
      <HeroHeader />
      <h1 className="screen-title">Your Workouts</h1>
      {startError && <div className="error-banner">{startError}</div>}
      <div className="workout-list">
        {dashboard.workouts.map((workout) => (
          <WorkoutPanel
            key={workout.session_id}
            workout={workout}
            timerLabel={timerLabel}
            onStart={() => void start(workout)}
          />
        ))}
      </div>
      {dashboard.coach_notes && <p className="dashboard-coach-notes">{dashboard.coach_notes}</p>}
    </div>
  )
}
