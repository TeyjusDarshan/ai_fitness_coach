import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAppState } from '../state/AppStateContext'
import { completeDay } from '../api'
import { buildCoachShareMessage, capitalize, coachWhatsAppShareUrl, formatDuration } from '../utils'
import type { DayCompleteSummary } from '../types'

export function SummaryScreen() {
  const { dashboard, username, refreshDashboard } = useAppState()
  const navigate = useNavigate()
  const { dayNumber } = useParams()
  const dayNum = Number(dayNumber)

  const [summary, setSummary] = useState<DayCompleteSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const fired = useRef(false)

  useEffect(() => {
    if (fired.current || !dashboard) return
    fired.current = true
    completeDay(dashboard.session_id, dayNum)
      .then(setSummary)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to complete this day.'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboard])

  async function handleBackToDashboard() {
    try {
      await refreshDashboard()
    } catch {
      // No unfinished session left to fetch — e.g. this was the plan's last
      // remaining day and it just auto-completed the whole plan. Navigate
      // anyway; the dashboard screen's own error state (with a "try a
      // different username" fallback) takes over from here.
    }
    navigate('/', { replace: true })
  }

  if (error) {
    return (
      <div className="screen">
        <div className="error-banner">{error}</div>
        <button className="btn-secondary" onClick={handleBackToDashboard}>
          Back to Dashboard
        </button>
      </div>
    )
  }

  if (!summary) {
    return (
      <div className="screen">
        <div className="spinner" />
      </div>
    )
  }

  const day = dashboard?.days.find((d) => d.day_number === dayNum)

  function handleShareWithCoach() {
    if (!day || !summary || !dashboard) return
    const message = buildCoachShareMessage(day, summary, username, dashboard.session_id)
    window.open(coachWhatsAppShareUrl(message), '_blank', 'noopener,noreferrer')
  }

  return (
    <div className="screen summary-screen">
      <div className="card summary-card">
        <div className="summary-card__confetti" aria-hidden>
          🎉 🎊 🎉
        </div>
        <h1 className="summary-card__title">CONGRATULATIONS!</h1>
        {summary.plan_completed && (
          <p className="summary-card__plan-complete">You've completed your whole plan! 🎉</p>
        )}
        <div className="summary-card__name">{username ? capitalize(username) : ''}</div>
        <div className="summary-card__avatar" aria-hidden>🙂</div>

        <dl className="summary-card__stats">
          <div className="summary-card__stat">
            <dt>Total Time:</dt>
            <dd>{formatDuration(summary.total_time_seconds)}</dd>
          </div>
          <div className="summary-card__stat">
            <dt>Exercises Completed:</dt>
            <dd>{summary.exercises_completed}</dd>
          </div>
          <div className="summary-card__stat">
            <dt>Sets:</dt>
            <dd>{summary.sets_completed}</dd>
          </div>
          <div className="summary-card__stat">
            <dt>Avg. Rest:</dt>
            <dd>Placeholder</dd>
          </div>
          <div className="summary-card__stat">
            <dt>Pace:</dt>
            <dd>Placeholder</dd>
          </div>
        </dl>
      </div>

      {day && (
        <button className="btn-whatsapp" onClick={handleShareWithCoach}>
          Share Session with Coach
        </button>
      )}

      <button className="btn-primary" onClick={handleBackToDashboard}>
        Back to Dashboard
      </button>
    </div>
  )
}
