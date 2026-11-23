import { DEFAULT_TIMEZONE } from '../timezones'
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
import { fetchAppStart, logoutRequest, type Gender, type Me } from '../auth'
import { preloadHomeAssets } from '../preload'
import type { Dashboard, DashboardWorkout, PastWorkoutsPage } from '../types'

type DashboardStatus = 'idle' | 'loading' | 'loaded' | 'error'

// The Your Workouts page's Past tab loads this many at a time (the
// backend allows up to 20).
const PAST_PAGE_SIZE = 10
// A dashboard loaded this recently counts as fresh (refreshDashboard's skipIfFresh).
const FRESH_MS = 10_000

export type PastTotals = Omit<PastWorkoutsPage, 'workouts'>
export type AuthStatus = 'checking' | 'signedIn' | 'signedOut'

interface AppState {
  authStatus: AuthStatus
  userId: string | null
  // What to call the user on screen: their name, or their user_id if they
  // don't have one on file.
  displayName: string | null
  gender: Gender | null
  // Whether the coach switched diet tracking on for this user.
  dietEnabled: boolean
  // Whether they finished the one-time diet setup; until then /food sends
  // them to /food/setup.
  dietSetupDone: boolean
  markDietSetupDone: () => void
  // Their time zone (user_profiles.timezone): what "today" is for food.
  // Workout dates still follow India time.
  timezone: string
  // She confirmed a new time zone (see TimezoneCheck).
  setTimezone: (timezone: string) => void
  dashboard: Dashboard | null
  loading: boolean
  error: string | null
  dashboardStatus: DashboardStatus
  completeSignIn: (me: Me) => void
  logout: () => Promise<void>
  // `skipIfFresh`: do nothing when the dashboard was loaded moments ago
  // (e.g. by the start-up call just before the dashboard opened).
  refreshDashboard: (options?: { skipIfFresh?: boolean }) => Promise<void>
  setDashboard: (dashboard: Dashboard) => void
  updateDashboard: (updater: (prev: Dashboard) => Dashboard) => void
  // Past workouts loaded so far (newest first) and the totals across all of
  // them, fetched only when the Your Workouts page's Past tab is opened
  // (loadPast). Kept here so a past workout can still be opened on its
  // detail screen.
  pastWorkouts: DashboardWorkout[]
  pastTotals: PastTotals | null
  pastLoading: boolean
  pastError: string | null
  // Loads the first page, unless it's already loaded (or loading).
  loadPast: () => Promise<void>
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
  const [dietEnabled, setDietEnabled] = useState(false)
  const [dietSetupDone, setDietSetupDone] = useState(false)
  const [timezone, setTimezone] = useState(DEFAULT_TIMEZONE)
  const markDietSetupDone = useCallback(() => setDietSetupDone(true), [])
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
  // When the dashboard was last loaded (ms), for refreshDashboard's skipIfFresh.
  const loadedAt = useRef(0)
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

  // Start-up: one call for who's signed in and her dashboard, while the
  // plant and illustrations load alongside, so the dashboard opens complete
  // instead of filling in piece by piece.
  useEffect(() => {
    setUnauthorizedHandler(resetToSignedOut)
    Promise.all([fetchAppStart(), preloadHomeAssets()])
      .then(([start]) => {
        const { me, dashboard: data, dashboard_error: dashboardError } = start
        setUserId(me.user_id)
        setUserName(me.name)
        setGender(me.gender)
        setDietEnabled(me.diet_enabled === true)
        setDietSetupDone(me.diet_setup_done === true)
        setTimezone(me.timezone || DEFAULT_TIMEZONE)
        if (data) {
          setDashboard(data)
          setDashboardStatus('loaded')
          loadedAt.current = Date.now()
        } else {
          setDashboardStatus('error')
          setError(dashboardError?.error ?? 'Something went wrong.')
        }
        setAuthStatus('signedIn')
      })
      .catch(resetToSignedOut)
    return () => setUnauthorizedHandler(null)
  }, [resetToSignedOut])

  const completeSignIn = useCallback((me: Me) => {
    setUserId(me.user_id)
    setUserName(me.name)
    setGender(me.gender)
    setDietEnabled(me.diet_enabled === true)
    setDietSetupDone(me.diet_setup_done === true)
    setTimezone(me.timezone || DEFAULT_TIMEZONE)
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

  // Past workouts are fetched only for the Past tab. Best-effort: a failure
  // is shown on that tab.
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
  const loadPast = useCallback(async () => {
    if (pastTotals === null && !pastLoading) await loadPastPage(0)
  }, [loadPastPage, pastTotals, pastLoading])

  const refreshDashboard = useCallback(async (options?: { skipIfFresh?: boolean }) => {
    if (!userId || fetchInFlight.current) return
    if (options?.skipIfFresh && Date.now() - loadedAt.current < FRESH_MS) return
    // Her history may have changed too (a workout finished): the Past tab
    // fetches it again next time it's opened.
    setPastWorkouts([])
    setPastTotals(null)
    setPastError(null)
    fetchInFlight.current = true
    setLoading(true)
    setError(null)
    setDashboardStatus('loading')
    try {
      const data = await fetchDashboard(userId)
      setDashboard(data)
      setDashboardStatus('loaded')
      loadedAt.current = Date.now()
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
  }, [userId])

  const updateDashboard = useCallback((updater: (prev: Dashboard) => Dashboard) => {
    setDashboard((prev) => (prev ? updater(prev) : prev))
  }, [])

  const value = useMemo(
    () => ({
      authStatus,
      userId,
      displayName: userName ?? userId,
      gender,
      dietEnabled,
      dietSetupDone,
      markDietSetupDone,
      timezone,
      setTimezone,
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
      loadPast,
      loadMorePast,
    }),
    [
      authStatus,
      userId,
      userName,
      gender,
      dietEnabled,
      dietSetupDone,
      markDietSetupDone,
      timezone,
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
      loadPast,
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
