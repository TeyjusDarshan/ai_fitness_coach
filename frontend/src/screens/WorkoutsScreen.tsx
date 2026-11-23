import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { BUILD_LABEL } from '../buildInfo'
import { WorkoutRow } from '../components/DashboardCards'
import { Icon } from '../components/Icon'
import { useAppState } from '../state/AppStateContext'

type Tab = 'upcoming' | 'past'

/** "See All": every upcoming workout of this plan, and her past workouts across all plans (paged). */
export function WorkoutsScreen() {
  const {
    dashboard,
    loading,
    error,
    refreshDashboard,
    pastWorkouts,
    pastTotals,
    pastLoading,
    pastError,
    loadMorePast,
  } = useAppState()
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('upcoming')

  useEffect(() => {
    // Opened directly (reload, link): load the dashboard, which also loads the first past page.
    if (!dashboard) refreshDashboard().catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const sessionMinutes = dashboard?.session_duration_minutes ?? null
  const upcoming = (dashboard?.workouts ?? []).filter((w) => w.status === 'scheduled')
  const hasMorePast = pastTotals !== null && pastWorkouts.length < pastTotals.total

  return (
    <div className="screen workouts-screen">
      <header className="page-header">
        <button className="page-header__back" onClick={() => navigate('/')} aria-label="Back">
          <Icon name="chevronLeft" size={22} />
        </button>
        <h1 className="page-header__title">Your Workouts</h1>
      </header>

      <div className="segmented" role="tablist">
        {(['upcoming', 'past'] as const).map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            className={`segmented__tab${tab === t ? ' segmented__tab--active' : ''}`}
            onClick={() => setTab(t)}
          >
            {t === 'upcoming' ? `Upcoming${dashboard ? ` (${upcoming.length})` : ''}` : 'Past'}
          </button>
        ))}
      </div>

      {error && !dashboard && <div className="error-banner">{error}</div>}
      {loading && !dashboard && <div className="spinner" />}

      {tab === 'upcoming' && dashboard && (
        <div className="workout-rows">
          {upcoming.length === 0 && <p className="home-section__empty">Nothing scheduled — enjoy the break.</p>}
          {upcoming.map((w) => (
            <WorkoutRow key={w.session_id} workout={w} sessionMinutes={sessionMinutes} />
          ))}
        </div>
      )}

      {tab === 'past' && (
        <div className="workout-rows">
          {pastTotals && (
            <p className="workouts-screen__counts">
              {pastTotals.completed} completed{pastTotals.missed > 0 ? ` · ${pastTotals.missed} missed` : ''}
            </p>
          )}
          {pastTotals?.total === 0 && <p className="home-section__empty">No past workouts yet.</p>}
          {pastWorkouts.map((w) => (
            <WorkoutRow key={w.session_id} workout={w} sessionMinutes={sessionMinutes} />
          ))}
          {pastError && <div className="error-banner">{pastError}</div>}
          {hasMorePast && (
            <button className="btn-secondary load-more" disabled={pastLoading} onClick={() => void loadMorePast()}>
              {pastLoading ? 'Loading…' : 'Load more'}
            </button>
          )}
        </div>
      )}

      <p className="build-version">{BUILD_LABEL}</p>
    </div>
  )
}
