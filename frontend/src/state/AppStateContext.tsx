import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { fetchDashboard, fetchPastWorkouts, setUnauthorizedHandler } from '../api'
import { fetchMe, logoutRequest, type Gender, type Me } from '../auth'
import type { Dashboard, DashboardWorkout, PastWorkoutsPage } from '../types'

type DashboardStatus = 'idle' | 'loading' | 'loaded' | 'error'

// The dashboard's Past Workouts list loads this many at a time.
const PAST_PAGE_SIZE = 2

export type PastTotals = Omit<PastWorkoutsPage, 'workouts'>
export type AuthStatus = 'checking' | 'signedIn' | 'signedOut'

interface AppState {
  authStatus: AuthStatus
  userId: string | null
  // What to call the user on screen: their name, or their user_id if they
  // don't have one on file.
  displayName: string | null
  gender: Gender | null
  dashboard: Dashboard | null
  loading: boolean
  error: string | null
  dashboardStatus: DashboardStatus
  completeSignIn: (me: Me) => void
  logout: () => Promise<void>
  refreshDashboard: () => Promise<void>
  setDashboard: (dashboard: Dashboard) => void
  updateDashboard: (updater: (prev: Dashboard) => Dashboard) => void
  // Past workouts loaded so far (newest first) and the totals across all of
  // them. Kept here, not on the dashboard screen, so a past workout loaded
  // through "Load more" can still be opened on its detail screen.
  pastWorkouts: DashboardWorkout[]
  pastTotals: PastTotals | null
  pastLoading: boolean
  pastError: string | null
  loadMorePast: () => Promise<void>
}

const AppStateContext = createContext<AppState | null>(null)

export function AppStateProvider({ children }: { children: ReactNode }) {
  // The session itself lives in an HttpOnly cookie the JS can't read, so on
  // boot we ask the server who (if anyone) is signed in.
  const [authStatus, setAuthStatus] = useState<AuthStatus>('checking')
  const [userId, setUserId] = useState<string | null>(null)
  const [userName, setUserName] = useState<string | null>(null)
  const [gender, setGender] = useState<Gender | null>(null)
  const [dashboard, setDashboard] = useState<Dashboard | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Tracks whether a dashboard fetch has already been attempted this session,
  // independent of `dashboard` (which gets cleared back to null on failure).
  // Without this, any remount (route navigation, StrictMode) reads "no
  // dashboard yet" as "haven't tried yet" and refetches forever after a
  // persistent 404.
  const [dashboardStatus, setDashboardStatus] = useState<DashboardStatus>('idle')
  // Synchronous guard so concurrent/StrictMode-doubled calls collapse into
  // one in-flight request instead of firing duplicate network calls.
  const fetchInFlight = useRef(false)
  const [pastWorkouts, setPastWorkouts] = useState<DashboardWorkout[]>([])
  const [pastTotals, setPastTotals] = useState<PastTotals | null>(null)
  const [pastLoading, setPastLoading] = useState(false)
  const [pastError, setPastError] = useState<string | null>(null)

  const resetToSignedOut = useCallback(() => {
    setUserId(null)
    setUserName(null)
    setGender(null)
    setDashboard(null)
    setError(null)
    setDashboardStatus('idle')
    setPastWorkouts([])
    setPastTotals(null)
    setAuthStatus('signedOut')
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(resetToSignedOut)
    fetchMe()
      .then((me) => {
        setUserId(me.user_id)
        setUserName(me.name)
        setGender(me.gender)
        setAuthStatus('signedIn')
      })
      .catch(resetToSignedOut)
    return () => setUnauthorizedHandler(null)
  }, [resetToSignedOut])

  const completeSignIn = useCallback((me: Me) => {
    setUserId(me.user_id)
    setUserName(me.name)
    setGender(me.gender)
    setDashboard(null)
    setError(null)
    setDashboardStatus('idle')
    setPastWorkouts([])
    setPastTotals(null)
    setAuthStatus('signedIn')
  }, [])

  const logout = useCallback(async () => {
    try {
      await logoutRequest()
    } finally {
      resetToSignedOut()
    }
  }, [resetToSignedOut])

  // Past workouts start over from the first page whenever the dashboard is
  // refreshed. Best-effort: a failure here leaves the rest of the dashboard
  // working and is shown in the Past section instead.
  const loadPastPage = useCallback(
    async (offset: number) => {
      if (!userId) return
      setPastLoading(true)
      setPastError(null)
      try {
        const page = await fetchPastWorkouts(userId, offset, PAST_PAGE_SIZE)
        setPastWorkouts((prev) => (offset === 0 ? page.workouts : [...prev, ...page.workouts]))
        setPastTotals({ total: page.total, completed: page.completed, missed: page.missed })
      } catch (e) {
        setPastError(e instanceof Error ? e.message : 'Could not load past workouts.')
      } finally {
        setPastLoading(false)
      }
    },
    [userId],
  )

  const loadMorePast = useCallback(() => loadPastPage(pastWorkouts.length), [loadPastPage, pastWorkouts.length])

  const refreshDashboard = useCallback(async () => {
    if (!userId || fetchInFlight.current) return
    void loadPastPage(0)
    fetchInFlight.current = true
    setLoading(true)
    setError(null)
    setDashboardStatus('loading')
    try {
      const data = await fetchDashboard(userId)
      setDashboard(data)
      setDashboardStatus('loaded')
    } catch (e) {
      // Clear stale data rather than leaving an outdated dashboard on
      // screen — e.g. once a plan's last day completes, this 404s (no more
      // unfinished session), and a stale dashboard would otherwise keep
      // showing an already-finished day as still pending.
      setDashboard(null)
      setDashboardStatus('error')
      setError(e instanceof Error ? e.message : 'Something went wrong.')
      throw e
    } finally {
      setLoading(false)
      fetchInFlight.current = false
    }
  }, [userId, loadPastPage])

  const updateDashboard = useCallback((updater: (prev: Dashboard) => Dashboard) => {
    setDashboard((prev) => (prev ? updater(prev) : prev))
  }, [])

  const value = useMemo(
    () => ({
      authStatus,
      userId,
      displayName: userName ?? userId,
      gender,
      dashboard,
      loading,
      error,
      dashboardStatus,
      completeSignIn,
      logout,
      refreshDashboard,
      setDashboard,
      updateDashboard,
      pastWorkouts,
      pastTotals,
      pastLoading,
      pastError,
      loadMorePast,
    }),
    [
      authStatus,
      userId,
      userName,
      gender,
      dashboard,
      loading,
      error,
      dashboardStatus,
      completeSignIn,
      logout,
      refreshDashboard,
      updateDashboard,
      pastWorkouts,
      pastTotals,
      pastLoading,
      pastError,
      loadMorePast,
    ],
  )

  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>
}

export function useAppState(): AppState {
  const ctx = useContext(AppStateContext)
  if (!ctx) throw new Error('useAppState must be used within AppStateProvider')
  return ctx
}
