import { useEffect } from 'react'
import { CollapsibleSection } from '../components/CollapsibleSection'
import { LevelCard } from '../components/LevelCard'
import { PlantHero } from '../components/PlantHero'
import { Icon } from '../components/Icon'
import { WorkoutPanel } from '../components/WorkoutPanel'
import { useAppState } from '../state/AppStateContext'
import { BUILD_LABEL } from '../buildInfo'
import { PeriodPrompt } from '../components/PeriodPrompt'
import { useStartWorkout } from '../state/useStartWorkout'
import { appTodayIso, formatDayDate } from '../utils'
import { levelForPoints } from '../plant3d/levels'

export function DashboardScreen() {
  const {
    userId,
    displayName,
    dashboard,
    loading,
    error,
    refreshDashboard,
    logout,
    pastWorkouts,
    pastTotals,
    pastLoading,
    pastError,
    loadMorePast,
  } = useAppState()
  const { start, error: startError, periodPrompt } = useStartWorkout()

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

  // The Today card: today's workout (scheduled, in progress or completed),
  // or on a rest day the next scheduled one.
  const today = dashboard.workouts.find((w) => w.is_today)
  const featured = today ?? dashboard.workouts.find((w) => w.is_next)
  const upcoming = dashboard.workouts.filter((w) => w.status === 'scheduled' && w !== featured)
  // Today's completed workout is already the Today card, so the Past list
  // and its count leave it out.
  const past = pastWorkouts.filter((w) => !w.is_today)
  const todayIsPast = today?.status === 'completed' ? 1 : 0
  const pastCompleted = (pastTotals?.completed ?? 0) - todayIsPast
  const pastMissed = pastTotals?.missed ?? 0
  const hasMorePast = pastTotals !== null && pastWorkouts.length < pastTotals.total

  const subtitle = !today
    ? 'No workout today. Check below for upcoming and past sessions.'
    : today.status === 'completed'
      ? 'Great job today! Check below for upcoming and past sessions.'
      : "Today's workout is ready. Check below for upcoming and past sessions."

  const plantLevel = levelForPoints(dashboard.points ?? 0)

  const panel = (workout: (typeof dashboard.workouts)[number]) => (
    <WorkoutPanel
      key={workout.session_id}
      workout={workout}
      timerLabel={timerLabel}
      onStart={() => void start(workout)}
    />
  )

  return (
    <div className="screen dashboard-screen">
      <PlantHero name={displayName ?? ''} userId={userId ?? ''} step={plantLevel.level} />
      <LevelCard points={dashboard.points ?? 0} plantLevel={plantLevel} />

      {/* Only this part scrolls; the plant and level card stay put. */}
      <div className="dashboard__scroll">
        <h2 className="screen-title">Your Workouts</h2>
        <p className="dashboard__subtitle">{subtitle}</p>
        {startError && <div className="error-banner">{startError}</div>}

        <div className="today-row">
          <span className="today-chip">
            <Icon name="calendar" size={20} />
            Today
          </span>
          <span className="today-row__date">{formatDayDate(appTodayIso())}</span>
        </div>
        {!today && <p className="dashboard__rest">Rest day today — enjoy the break.</p>}
        {featured && <div className="workout-list">{panel(featured)}</div>}

        {upcoming.length > 0 && (
          <CollapsibleSection
            title="Upcoming Workouts"
            summary={`${upcoming.length} scheduled`}
            icon="calendar"
            variant="upcoming"
          >
            <div className="workout-list">{upcoming.map(panel)}</div>
          </CollapsibleSection>
        )}

        {(past.length > 0 || hasMorePast || pastError) && (
          <CollapsibleSection
            title="Past Workouts"
            summary={
              pastTotals
                ? `${pastCompleted} completed${pastMissed > 0 ? ` · ${pastMissed} missed` : ''}`
                : 'Could not load'
            }
            icon="clock"
            variant="past"
          >
            <div className="workout-list">{past.map(panel)}</div>
            {pastError && <div className="error-banner">{pastError}</div>}
            {hasMorePast && (
              <button className="btn-secondary load-more" disabled={pastLoading} onClick={() => void loadMorePast()}>
                {pastLoading ? 'Loading…' : 'Load more'}
              </button>
            )}
          </CollapsibleSection>
        )}
        {dashboard.coach_notes && <p className="dashboard-coach-notes">{dashboard.coach_notes}</p>}
        <p className="build-version">{BUILD_LABEL}</p>
      </div>
      <PeriodPrompt {...periodPrompt} />
    </div>
  )
}
