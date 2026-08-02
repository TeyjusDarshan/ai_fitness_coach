import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { CircularCountdown } from '../components/CircularCountdown'
import { REST_BETWEEN_EXERCISES_SECONDS } from '../constants'

// Purely client-side: fixed countdown, no backend calls at all. Reused for
// both the between-set rest (1:30) and the between-exercise rest (0:30) —
// the caller supplies `seconds` and the `next` path to land on once the
// countdown ends (or the user taps Skip Rest).
export function RestTimerScreen() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const totalSeconds = Number(searchParams.get('seconds') ?? REST_BETWEEN_EXERCISES_SECONDS)
  const next = searchParams.get('next') ?? '/'

  const [secondsLeft, setSecondsLeft] = useState(totalSeconds)
  const advancedRef = useRef(false)

  function advance() {
    if (advancedRef.current) return
    advancedRef.current = true
    navigate(next, { replace: true })
  }

  useEffect(() => {
    if (secondsLeft <= 0) {
      advance()
      return
    }
    const timer = setTimeout(() => setSecondsLeft((s) => s - 1), 1000)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [secondsLeft])

  return (
    <div className="screen rest-screen">
      <div className="rest-screen__center">
        <div className="rest-screen__label">RESTING…</div>
        <CircularCountdown secondsLeft={secondsLeft} totalSeconds={totalSeconds} />
      </div>
      <button className="btn-link" onClick={advance}>
        Skip Rest
      </button>
    </div>
  )
}
