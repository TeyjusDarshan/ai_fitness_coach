import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { fetchDashboard } from '../api'
import { USERNAME_STORAGE_KEY } from '../constants'
import type { Dashboard } from '../types'

interface AppState {
  username: string | null
  dashboard: Dashboard | null
  loading: boolean
  error: string | null
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

  const login = useCallback(async (candidateUsername: string) => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchDashboard(candidateUsername)
      localStorage.setItem(USERNAME_STORAGE_KEY, candidateUsername)
      setUsername(candidateUsername)
      setDashboard(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.')
      throw e
    } finally {
      setLoading(false)
    }
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem(USERNAME_STORAGE_KEY)
    setUsername(null)
    setDashboard(null)
  }, [])

  const refreshDashboard = useCallback(async () => {
    if (!username) return
    setLoading(true)
    setError(null)
    try {
      const data = await fetchDashboard(username)
      setDashboard(data)
    } catch (e) {
      // Clear stale data rather than leaving an outdated dashboard on
      // screen — e.g. once a plan's last day completes, this 404s (no more
      // unfinished session), and a stale dashboard would otherwise keep
      // showing an already-finished day as still pending.
      setDashboard(null)
      setError(e instanceof Error ? e.message : 'Something went wrong.')
      throw e
    } finally {
      setLoading(false)
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
      login,
      logout,
      refreshDashboard,
      setDashboard,
      updateDashboard,
    }),
    [username, dashboard, loading, error, login, logout, refreshDashboard, updateDashboard],
  )

  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>
}

export function useAppState(): AppState {
  const ctx = useContext(AppStateContext)
  if (!ctx) throw new Error('useAppState must be used within AppStateProvider')
  return ctx
}
