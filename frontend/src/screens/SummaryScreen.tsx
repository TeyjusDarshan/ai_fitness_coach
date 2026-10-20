import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAppState } from '../state/AppStateContext'
import { completeSession } from '../api'
import { Icon } from '../components/Icon'
import { buildCoachShareMessage, capitalize, coachWhatsAppShareUrl, formatDuration } from '../utils'
import type { DayCompleteSummary } from '../types'

export function SummaryScreen() {
  const { dashboard, displayName, refreshDashboard } = useAppState()
  const navigate = useNavigate()
  const { dayNumber } = useParams()
  const dayNum = Number(dayNumber)

  const [summary, setSummary] = useState<DayCompleteSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const fired = useRef(false)

  useEffect(() => {
    if (fired.current || !dashboard) return
    const sessionId = dashboard.days.find((d) => d.day_number === dayNum)?.session_id
    if (sessionId == null) return
    fired.current = true
    completeSession(sessionId)
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
      // anyway; the dashboard screen's own error state (with a "Sign out"
      // fallback) takes over from here.
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
    const message = buildCoachShareMessage(day, summary, displayName)
    window.open(coachWhatsAppShareUrl(message), '_blank', 'noopener,noreferrer')
  }

  return (
    <div className="screen summary-screen">
      <div className="summary-card">
        <div className="summary-card__trophy">
          <span className="summary-card__confetti" aria-hidden>
            {Array.from({ length: 10 }, (_, i) => (
              <span key={i} className={`confetti confetti--${i}`} />
            ))}
          </span>
          <Laurel side="left" />
          <span className="summary-card__cup">
            <Icon name="trophy" size={76} />
          </span>
          <Laurel side="right" />
        </div>
        <h1 className="summary-card__title">Congratulations!</h1>
        {summary.plan_completed && (
          <p className="summary-card__plan-complete">You've completed your whole plan!</p>
        )}
        {displayName && <div className="summary-card__name">{capitalize(displayName)}</div>}
        <div className="summary-card__avatar" aria-hidden>
          🙂
        </div>
        <div className="summary-card__well-done">Well done!</div>
        <p className="summary-card__motto">
          Small steps every day
          <br />
          lead to big changes.
        </p>

        <dl className="summary-card__stats">
          <div className="summary-card__stat">
            <dt>
              <Icon name="clock" size={18} />
              Total Time:
            </dt>
            <dd>{formatDuration(summary.total_time_seconds)}</dd>
          </div>
          <div className="summary-card__stat">
            <dt>
              <Icon name="dumbbell" size={18} />
              Exercises Completed:
            </dt>
            <dd>{summary.exercises_completed}</dd>
          </div>
          <div className="summary-card__stat">
            <dt>
              <Icon name="layers" size={18} />
              Sets:
            </dt>
            <dd>{summary.sets_completed}</dd>
          </div>
        </dl>
      </div>

      {day && (
        <button className="btn-primary" onClick={handleShareWithCoach}>
          <Icon name="share" size={18} />
          Share Session with Coach
        </button>
      )}

      <button className="btn-secondary" onClick={handleBackToDashboard}>
        Back to Dashboard
      </button>
    </div>
  )
}

// A sprig of leaves either side of the trophy.
function Laurel({ side }: { side: 'left' | 'right' }) {
  return (
    <svg viewBox="0 0 30 60" className={`laurel laurel--${side}`} aria-hidden>
      <path d="M22 58C10 46 6 30 12 6" stroke="#5f9b78" strokeWidth="2.5" fill="none" strokeLinecap="round" />
      {[12, 24, 36, 48].map((y) => (
        <g key={y}>
          <ellipse cx={y < 30 ? 6 : 9} cy={y} rx="6" ry="3" transform={`rotate(-35 ${y < 30 ? 6 : 9} ${y})`} fill="#7fb38c" />
          <ellipse cx={y < 30 ? 17 : 21} cy={y - 4} rx="6" ry="3" transform={`rotate(35 ${y < 30 ? 17 : 21} ${y - 4})`} fill="#9cc49f" />
        </g>
      ))}
    </svg>
  )
}
