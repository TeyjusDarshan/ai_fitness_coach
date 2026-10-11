import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { DayRow } from '../components/DayRow'
import { startSession } from '../api'
import { useAppState } from '../state/AppStateContext'
import { firstIncompleteIndex } from '../utils'
import type { DashboardDay } from '../types'

export function DashboardScreen() {
  const { dashboard, loading, error, refreshDashboard, logout } = useAppState()
  const navigate = useNavigate()
  const [startError, setStartError] = useState<string | null>(null)

  useEffect(() => {
    refreshDashboard().catch(() => {
      // surfaced via `error`
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handleStart(day: DashboardDay) {
    if (day.session_id == null) return
    setStartError(null)
    try {
      await startSession(day.session_id)
    } catch (e) {
      // e.g. 409 when the day's scheduled date hasn't arrived in the app's
      // timezone yet, even though the device clock says it has.
      setStartError(e instanceof Error ? e.message : 'Could not start this workout.')
      return
    }
    const slotIndex = firstIncompleteIndex(day)
    navigate(`/day/${day.day_number}/exercise/${slotIndex}`)
  }

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
      <h1 className="screen-title">Weekly Calendar</h1>
      {startError && <div className="error-banner">{startError}</div>}
      <div className="card day-list">
        {dashboard.days.map((day) => (
          <DayRow
            key={day.day_number}
            day={day}
            timerLabel={timerLabel}
            onStart={() => handleStart(day)}
          />
        ))}
      </div>
      {dashboard.coach_notes && <p className="dashboard-coach-notes">{dashboard.coach_notes}</p>}
    </div>
  )
}
