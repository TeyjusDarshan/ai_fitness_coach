import { useEffect, useRef, useState } from 'react'
import { completeSession } from '../api'
import { useAppState } from './AppStateContext'
import type { DayCompleteSummary } from '../types'

/**
 * Marks day `dayNum`'s session completed (once per mount) and returns the
 * result. `handedOver` is a result an earlier screen already got — the grow
 * screen passes its result on to the summary — in which case nothing is called.
 */
export function useCompleteSession(dayNum: number, handedOver?: DayCompleteSummary | null) {
  const { dashboard } = useAppState()
  const [summary, setSummary] = useState<DayCompleteSummary | null>(handedOver ?? null)
  const [error, setError] = useState<string | null>(null)
  const fired = useRef(handedOver != null)

  useEffect(() => {
    if (fired.current || !dashboard) return
    const sessionId = dashboard.days.find((d) => d.day_number === dayNum)?.session_id
    if (sessionId == null) return
    fired.current = true
    completeSession(sessionId)
      .then(setSummary)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to complete this day.'))
  }, [dashboard, dayNum])

  return { summary, error }
}
