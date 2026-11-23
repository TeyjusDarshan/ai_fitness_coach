import { useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { CornerLeaves } from '../components/Garden'
import { GardenCard, TodayCard, WorkoutRow } from '../components/DashboardCards'
import { Icon } from '../components/Icon'
import { PeriodPrompt } from '../components/PeriodPrompt'
import { useAppState } from '../state/AppStateContext'
import { useStartWorkout } from '../state/useStartWorkout'

export function DashboardScreen() {
  const { userId, displayName, dashboard, loading, error, refreshDashboard, logout } = useAppState()
  const { start, error: startError, periodPrompt } = useStartWorkout()
  const navigate = useNavigate()

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

  // The hero card: today's workout (scheduled, in progress or completed),
  // or on a rest day the next scheduled one.
  const today = dashboard.workouts.find((w) => w.is_today)
  const featured = today ?? dashboard.workouts.find((w) => w.is_next)
  const nextUpcoming = dashboard.workouts.find((w) => w.status === 'scheduled' && w !== featured)
  const sessionMinutes = dashboard.session_duration_minutes

  const subtitle = !today
    ? 'Rest day today — enjoy the break.'
    : today.status === 'completed'
      ? 'Great job today!'
      : "Ready for today's workout?"

  return (
    <div className="screen home-screen">
      <header className="home-header">
        <h1 className="home-header__greeting">
          Hi {displayName ?? ''} <span aria-hidden>👋</span>
        </h1>
        <p className="home-header__subtitle">{subtitle}</p>
      </header>

      {startError && <div className="error-banner">{startError}</div>}

      <TodayCard
        workout={featured}
        isToday={!!today}
        weekNumber={dashboard.week_number ?? 1}
        sessionMinutes={sessionMinutes}
        coachNotes={dashboard.coach_notes}
        onStart={() => featured && void start(featured)}
      />

      <GardenCard xp={dashboard.points ?? 0} userId={userId ?? ''} onOpen={() => navigate('/garden')} />

      <div className="home-section">
        <h2 className="home-section__title">Upcoming Workouts</h2>
        <Link className="home-section__link" to="/workouts">
          See All <Icon name="arrowRight" size={18} />
        </Link>
      </div>
      {nextUpcoming ? (
        <WorkoutRow workout={nextUpcoming} sessionMinutes={sessionMinutes} />
      ) : (
        <p className="home-section__empty">Nothing else scheduled this week.</p>
      )}

      <CornerLeaves className="corner-leaves--page" />
      <PeriodPrompt {...periodPrompt} />
    </div>
  )
}
