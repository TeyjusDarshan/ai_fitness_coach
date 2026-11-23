import { useEffect, type ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { useAppState } from './state/AppStateContext'
import { EnrollScreen } from './screens/EnrollScreen'
import { LoginScreen } from './screens/LoginScreen'
import { DashboardScreen } from './screens/DashboardScreen'
import { GardenScreen } from './screens/GardenScreen'
import { WorkoutsScreen } from './screens/WorkoutsScreen'
import { ExerciseScreen } from './screens/ExerciseScreen'
import { ExerciseFeedbackScreen } from './screens/ExerciseFeedbackScreen'
import { RestTimerScreen } from './screens/RestTimerScreen'
import { SummaryScreen } from './screens/SummaryScreen'
import { GrowScreen } from './screens/GrowScreen'
import { RoutineVideoScreen } from './screens/RoutineVideoScreen'
import { WorkoutDetailScreen } from './screens/WorkoutDetailScreen'
import { CardioScreen } from './screens/CardioScreen'
import { CardioRatingScreen } from './screens/CardioRatingScreen'
import { AdminScreen } from './screens/admin/AdminScreen'
import { DietSetupScreen } from './screens/DietSetupScreen'
import { FoodScreen } from './screens/FoodScreen'
import { MealReviewScreen } from './screens/MealReviewScreen'
import { MealItemScreen } from './screens/MealItemScreen'
import { BottomNav } from './components/BottomNav'
import { TimezoneCheck } from './components/TimezoneCheck'

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

// The Food screens exist only for clients the coach switched diet tracking
// on for; anyone else is sent back to the dashboard. Until she finishes the
// one-time setup every Food screen sends her to it, and the setup screen
// sends her on to /food once it's done.
function RequireDiet({ children, setup = false }: { children: ReactNode; setup?: boolean }) {
  const { authStatus, dietEnabled, dietSetupDone } = useAppState()
  if (authStatus === 'signedIn' && !dietEnabled) return <Navigate to="/" replace />
  if (authStatus === 'signedIn' && dietSetupDone === setup) {
    return <Navigate to={setup ? '/food' : '/food/setup'} replace />
  }
  return <RequireAuth>{children}</RequireAuth>
}

function RedirectIfSignedIn({ children }: { children: ReactNode }) {
  const { authStatus } = useAppState()
  if (authStatus === 'checking') return <Spinner />
  if (authStatus === 'signedIn') return <Navigate to="/" replace />
  return <>{children}</>
}

function App() {
  return (
    <>
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
          path="/workouts"
          element={
            <RequireAuth>
              <WorkoutsScreen />
            </RequireAuth>
          }
        />
        <Route
          path="/garden"
          element={
            <RequireAuth>
              <GardenScreen />
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
          path="/day/:dayNumber/exercise/:slotIndex/feedback"
          element={
            <RequireAuth>
              <ExerciseFeedbackScreen />
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
          path="/day/:dayNumber/cardio"
          element={
            <RequireAuth>
              <CardioScreen />
            </RequireAuth>
          }
        />
        <Route
          path="/day/:dayNumber/cardio/rate"
          element={
            <RequireAuth>
              <CardioRatingScreen />
            </RequireAuth>
          }
        />
        <Route
          path="/day/:dayNumber/grow"
          element={
            <RequireAuth>
              <GrowScreen />
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
          path="/food"
          element={
            <RequireDiet>
              <FoodScreen />
            </RequireDiet>
          }
        />
        <Route
          path="/food/setup"
          element={
            <RequireDiet setup>
              <DietSetupScreen />
            </RequireDiet>
          }
        />
        <Route
          path="/food/log/:logId"
          element={
            <RequireDiet>
              <MealReviewScreen />
            </RequireDiet>
          }
        />
        <Route
          path="/food/item/:itemId"
          element={
            <RequireDiet>
              <MealItemScreen />
            </RequireDiet>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <BottomNav />
      <TimezoneCheck />
    </>
  )
}

export default App
