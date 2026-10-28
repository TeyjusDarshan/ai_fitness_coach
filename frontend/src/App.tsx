import { useEffect, type ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { useAppState } from './state/AppStateContext'
import { EnrollScreen } from './screens/EnrollScreen'
import { LoginScreen } from './screens/LoginScreen'
import { DashboardScreen } from './screens/DashboardScreen'
import { ExerciseScreen } from './screens/ExerciseScreen'
import { RestTimerScreen } from './screens/RestTimerScreen'
import { FeedbackScreen } from './screens/FeedbackScreen'
import { SummaryScreen } from './screens/SummaryScreen'
import { RoutineVideoScreen } from './screens/RoutineVideoScreen'
import { WorkoutDetailScreen } from './screens/WorkoutDetailScreen'
import { AdminScreen } from './screens/admin/AdminScreen'

function Spinner() {
  return (
    <div className="screen">
      <div className="spinner" />
    </div>
  )
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { authStatus, dashboard, loading, dashboardStatus, refreshDashboard } = useAppState()

  useEffect(() => {
    // Only fetch on the first mount for this session. Gating on
    // `dashboardStatus === 'idle'` (rather than `!dashboard`) means a
    // definitive failure (e.g. 404) is remembered and won't be re-fetched
    // on every subsequent remount — route navigation remounts RequireAuth
    // separately per route, which previously turned a single 404 into a
    // fetch on every screen change.
    if (authStatus === 'signedIn' && dashboardStatus === 'idle') {
      refreshDashboard().catch(() => {
        // surfaced via useAppState().error, handled by DashboardScreen
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authStatus, dashboardStatus])

  if (authStatus === 'checking') return <Spinner />
  if (authStatus === 'signedOut') return <Navigate to="/login" replace />
  if (!dashboard && loading) return <Spinner />
  return <>{children}</>
}

function RedirectIfSignedIn({ children }: { children: ReactNode }) {
  const { authStatus } = useAppState()
  if (authStatus === 'checking') return <Spinner />
  if (authStatus === 'signedIn') return <Navigate to="/" replace />
  return <>{children}</>
}

function App() {
  return (
    <Routes>
      <Route
        path="/login"
        element={
          <RedirectIfSignedIn>
            <LoginScreen />
          </RedirectIfSignedIn>
        }
      />
      <Route path="/enroll" element={<EnrollScreen />} />
      <Route path="/admin" element={<AdminScreen />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <DashboardScreen />
          </RequireAuth>
        }
      />
      <Route
        path="/workout/:sessionId"
        element={
          <RequireAuth>
            <WorkoutDetailScreen />
          </RequireAuth>
        }
      />
      <Route
        path="/day/:dayNumber/warmup"
        element={
          <RequireAuth>
            <RoutineVideoScreen kind="warmup" />
          </RequireAuth>
        }
      />
      <Route
        path="/day/:dayNumber/cooldown"
        element={
          <RequireAuth>
            <RoutineVideoScreen kind="cooldown" />
          </RequireAuth>
        }
      />
      <Route
        path="/day/:dayNumber/exercise/:slotIndex"
        element={
          <RequireAuth>
            <ExerciseScreen />
          </RequireAuth>
        }
      />
      <Route
        path="/day/:dayNumber/rest"
        element={
          <RequireAuth>
            <RestTimerScreen />
          </RequireAuth>
        }
      />
      <Route
        path="/day/:dayNumber/summary"
        element={
          <RequireAuth>
            <SummaryScreen />
          </RequireAuth>
        }
      />
      <Route
        path="/day/:dayNumber/feedback"
        element={
          <RequireAuth>
            <FeedbackScreen />
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
