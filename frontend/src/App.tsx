import { useEffect, type ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { useAppState } from './state/AppStateContext'
import { LoginScreen } from './screens/LoginScreen'
import { DashboardScreen } from './screens/DashboardScreen'
import { ExerciseScreen } from './screens/ExerciseScreen'
import { RestTimerScreen } from './screens/RestTimerScreen'
import { SummaryScreen } from './screens/SummaryScreen'

function RequireAuth({ children }: { children: ReactNode }) {
  const { username, dashboard, loading, dashboardStatus, refreshDashboard } = useAppState()

  useEffect(() => {
    // Only fetch on the first mount for this session. Gating on
    // `dashboardStatus === 'idle'` (rather than `!dashboard`) means a
    // definitive failure (e.g. 404) is remembered and won't be re-fetched
    // on every subsequent remount — route navigation remounts RequireAuth
    // separately per route, which previously turned a single 404 into a
    // fetch on every screen change.
    if (username && dashboardStatus === 'idle') {
      refreshDashboard().catch(() => {
        // surfaced via useAppState().error, handled by DashboardScreen
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [username, dashboardStatus])

  if (!username) {
    return <Navigate to="/login" replace />
  }
  if (!dashboard && loading) {
    return (
      <div className="screen">
        <div className="spinner" />
      </div>
    )
  }
  return <>{children}</>
}

function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginScreen />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <DashboardScreen />
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
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
