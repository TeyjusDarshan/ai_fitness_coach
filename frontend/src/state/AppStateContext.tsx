import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { fetchDashboard } from '../api'
import { USERNAME_STORAGE_KEY } from '../constants'
import type { Dashboard } from '../types'

type DashboardStatus = 'idle' | 'loading' | 'loaded' | 'error'

interface AppState {
  username: string | null
  dashboard: Dashboard | null
  loading: boolean
  error: string | null
  dashboardStatus: DashboardStatus
  login: (username: string) => Promise<void>
  logout: () => void
  refreshDashboard: () => Promise<void>
  setDashboard: (dashboard: Dashboard) => void
  updateDashboard: (updater: (prev: Dashboard) => Dashboard) => void
}

const AppStateContext = createContext<AppState | null>(null)

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [username, setUsername] = useState<string | null>(() =>
    localStorage.getItem(USERNAME_STORAGE_KEY),
  )
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

  const login = useCallback(async (candidateUsername: string) => {
    if (fetchInFlight.current) return
    fetchInFlight.current = true
    setLoading(true)
    setError(null)
    setDashboardStatus('loading')
    try {
      const data = await fetchDashboard(candidateUsername)
      localStorage.setItem(USERNAME_STORAGE_KEY, candidateUsername)
      setUsername(candidateUsername)
      setDashboard(data)
      setDashboardStatus('loaded')
    } catch (e) {
      setDashboardStatus('error')
      setError(e instanceof Error ? e.message : 'Something went wrong.')
      throw e
    } finally {
      setLoading(false)
      fetchInFlight.current = false
    }
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem(USERNAME_STORAGE_KEY)
    setUsername(null)
    setDashboard(null)
    setDashboardStatus('idle')
  }, [])

  const refreshDashboard = useCallback(async () => {
    if (!username || fetchInFlight.current) return
    fetchInFlight.current = true
    setLoading(true)
    setError(null)
    setDashboardStatus('loading')
    try {
      const data = await fetchDashboard(username)
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
  }, [username])

  const updateDashboard = useCallback((updater: (prev: Dashboard) => Dashboard) => {
    setDashboard((prev) => (prev ? updater(prev) : prev))
  }, [])

  const value = useMemo(
    () => ({
      username,
      dashboard,
      loading,
      error,
      dashboardStatus,
      login,
      logout,
      refreshDashboard,
      setDashboard,
      updateDashboard,
    }),
    [
      username,
      dashboard,
      loading,
      error,
      dashboardStatus,
      login,
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
