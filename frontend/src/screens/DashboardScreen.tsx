import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { DayRow } from '../components/DayRow'
import { startDay } from '../api'
import { useAppState } from '../state/AppStateContext'
import { WEEKDAYS } from '../constants'
import { firstIncompleteIndex } from '../utils'
import type { DashboardDay } from '../types'

export function DashboardScreen() {
  const { dashboard, loading, error, refreshDashboard, logout } = useAppState()
  const navigate = useNavigate()

  useEffect(() => {
    refreshDashboard().catch(() => {
      // surfaced via `error`
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handleStart(day: DashboardDay) {
    if (!dashboard) return
    await startDay(dashboard.session_id, day.day_number)
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
        <button className="btn-secondary" onClick={logout}>
          Try a different username
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
      <div className="card day-list">
        {dashboard.days.map((day, i) => (
          <DayRow
            key={day.day_number}
            day={day}
            weekday={WEEKDAYS[i] ?? day.day_label}
            timerLabel={timerLabel}
            onStart={() => handleStart(day)}
          />
        ))}
      </div>
      {dashboard.coach_notes && <p className="dashboard-coach-notes">{dashboard.coach_notes}</p>}
    </div>
  )
}
