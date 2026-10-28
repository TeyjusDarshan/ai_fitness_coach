import { useEffect, useRef, useState } from 'react'

// Counts down `totalSeconds` while `running`, calling `onDone` once at zero.
// Time comes from timestamps, not tick counts, so it stays right when the
// tab is backgrounded or the phone is locked (timers are throttled then).
// Pausing (running=false) freezes it; changing `resetKey` (or the total)
// starts it over. Returns the milliseconds left.
export function useCountdown(totalSeconds: number, running: boolean, onDone: () => void, resetKey: unknown = null): number {
  const [msLeft, setMsLeft] = useState(totalSeconds * 1000)
  const baseMs = useRef(totalSeconds * 1000) // left when the current run began
  const startedAt = useRef<number | null>(null)
  const done = useRef(false)
  const onDoneRef = useRef(onDone)
  onDoneRef.current = onDone

  useEffect(() => {
    baseMs.current = totalSeconds * 1000
    startedAt.current = null
    done.current = false
    setMsLeft(totalSeconds * 1000)
  }, [totalSeconds, resetKey])

  useEffect(() => {
    if (!running) return
    startedAt.current = Date.now()
    const tick = () => {
      if (startedAt.current === null) return
      const left = Math.max(0, baseMs.current - (Date.now() - startedAt.current))
      setMsLeft(left)
      if (left === 0 && !done.current) {
        done.current = true
        onDoneRef.current()
      }
    }
    tick()
    const id = window.setInterval(tick, 200)
    document.addEventListener('visibilitychange', tick)
    return () => {
      window.clearInterval(id)
      document.removeEventListener('visibilitychange', tick)
      if (startedAt.current !== null) {
        baseMs.current = Math.max(0, baseMs.current - (Date.now() - startedAt.current))
        startedAt.current = null
      }
    }
  }, [running, totalSeconds, resetKey])

  return msLeft
}
