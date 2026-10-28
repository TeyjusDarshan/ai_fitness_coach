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
import { fetchDashboard, setUnauthorizedHandler } from '../api'
import { fetchMe, logoutRequest, type Gender, type Me } from '../auth'
import type { Dashboard } from '../types'

type DashboardStatus = 'idle' | 'loading' | 'loaded' | 'error'
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

  const resetToSignedOut = useCallback(() => {
    setUserId(null)
    setUserName(null)
    setGender(null)
    setDashboard(null)
    setError(null)
    setDashboardStatus('idle')
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
    setAuthStatus('signedIn')
  }, [])

  const logout = useCallback(async () => {
    try {
      await logoutRequest()
    } finally {
      resetToSignedOut()
    }
  }, [resetToSignedOut])

  const refreshDashboard = useCallback(async () => {
    if (!userId || fetchInFlight.current) return
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
      dashboard,
      loading,
      error,
      dashboardStatus,
      completeSignIn,
      logout,
      refreshDashboard,
      setDashboard,
      updateDashboard,
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
    ],
  )

  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>
}

export function useAppState(): AppState {
  const ctx = useContext(AppStateContext)
  if (!ctx) throw new Error('useAppState must be used within AppStateProvider')
  return ctx
}
