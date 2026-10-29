import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { logRpe, logSet } from '../api'
import { CircularCountdown } from '../components/CircularCountdown'
import { DEFAULT_RPE } from '../components/EffortSlider'
import { Icon } from '../components/Icon'
import { VideoPlayer } from '../components/VideoPlayer'
import { REST_BETWEEN_SETS_SECONDS } from '../constants'
import { useAppState } from '../state/AppStateContext'
import { useCountdown } from '../state/useCountdown'
import { playTick, unlockTickSound } from '../state/tickSound'
import { afterExercisePath, formatClock, targetRepsForSet, withRpeLogged, withSetLogged, withSetLogRemoved } from '../utils'
import type { DashboardDay, ExerciseEntry } from '../types'

// The 3-2-1 before each hold.
const GET_READY_SECONDS = 3

const DEFAULT_TIP = 'Keep your body in a straight line and breathe normally.'

// Easy / Moderate / Hard, stored as the same RPE values the rep screen's
// effort slider uses (see LEVELS in EffortSlider).
const DIFFICULTIES = [
  { label: 'Easy', rpe: 6, face: 'easy' },
  { label: 'Moderate', rpe: 8, face: 'moderate' },
  { label: 'Hard', rpe: 10, face: 'hard' },
] as const

type Phase = 'intro' | 'countdown' | 'active' | 'rest' | 'next-set' | 'done' | 'difficulty'

// A hold measured in seconds (exercises.is_time_based), run as a guided
// flow: intro → 3-2-1 → timer (pause / end early) → rest → "set complete"
// (waits for Start) → 3-2-1 → … → "Great job" → how hard was it → next
// exercise.
// Starts at the first set with no log, so reopening it resumes; each set's
// seconds held are logged as that set's completed_reps.
export function TimedExerciseScreen({
  day,
  exercise,
  slotIndex,
  exerciseCount,
}: {
  day: DashboardDay
  exercise: ExerciseEntry
  slotIndex: number
  exerciseCount: number
}) {
  const { updateDashboard } = useAppState()
  const navigate = useNavigate()
  const dayNum = day.day_number
  const totalSets = exercise.sets ?? 1

  const firstOpenSet = Array.from({ length: totalSets }, (_, i) => i).find(
    (i) => !exercise.set_logs.some((log) => log.set_number === i + 1),
  )
  const [setIdx, setSetIdx] = useState(firstOpenSet ?? totalSets - 1)
  const [phase, setPhase] = useState<Phase>(firstOpenSet === undefined ? 'done' : 'intro')
  const [paused, setPaused] = useState(false)
  const [lastHeld, setLastHeld] = useState(() => {
    const last = [...exercise.set_logs].sort((a, b) => b.set_number - a.set_number)[0]
    return last?.completed_reps ?? 0
  })
  // Preselects Moderate, matching the rep screen's effort slider default.
  const [difficulty, setDifficulty] = useState(exercise.rpe ?? DEFAULT_RPE)

  const target = targetRepsForSet(exercise, setIdx)
  const timerSeconds =
    phase === 'active' ? target : phase === 'rest' ? REST_BETWEEN_SETS_SECONDS : GET_READY_SECONDS
  const timing = phase === 'countdown' || phase === 'active' || phase === 'rest'

  const msLeft = useCountdown(timerSeconds, timing && !paused, handleTimerDone, `${phase}:${setIdx}`)
  const secondsLeft = Math.ceil(msLeft / 1000)

  // Tick once a second while she holds (not at the very start or at zero,
  // and not while paused).
  useEffect(() => {
    if (phase === 'active' && !paused && secondsLeft > 0 && secondsLeft < target) playTick()
  }, [phase, paused, secondsLeft, target])

  useWakeLock(timing)

  function handleTimerDone() {
    if (phase === 'countdown') setPhase('active')
    else if (phase === 'active') finishSet(target)
    else if (phase === 'rest') setPhase('next-set')
  }

  // The next set only begins when she's ready: Start leads into the 3-2-1.
  function startNextSet() {
    unlockTickSound()
    setSetIdx((i) => i + 1)
    setPhase('countdown')
  }

  function finishSet(held: number) {
    const setNumber = setIdx + 1
    const previousLog = exercise.set_logs.find((l) => l.set_number === setNumber)
    updateDashboard((prev) => withSetLogged(prev, dayNum, exercise.id, setNumber, held))
    // Fire-and-forget like the rep screen: revert the optimistic log if the
    // server refuses it.
    logSet(day.session_id!, exercise.id, setNumber, held).catch(() => {
      updateDashboard((prev) =>
        previousLog
          ? withSetLogged(prev, dayNum, exercise.id, setNumber, previousLog.completed_reps)
          : withSetLogRemoved(prev, dayNum, exercise.id, setNumber),
      )
    })
    navigator.vibrate?.(200)
    setLastHeld(held)
    setPaused(false)
    setPhase(setNumber < totalSets ? 'rest' : 'done')
  }

  function endEarly() {
    finishSet(Math.max(0, Math.round(target - msLeft / 1000)))
  }

  function finishExercise() {
    const previousRpe = exercise.rpe
    const previousLogged = !!exercise.rpe_logged
    updateDashboard((prev) => withRpeLogged(prev, dayNum, exercise.id, difficulty))
    logRpe(day.session_id!, exercise.id, difficulty).catch(() => {
      updateDashboard((prev) => withRpeLogged(prev, dayNum, exercise.id, previousRpe, previousLogged))
    })
    navigate(afterExercisePath(dayNum, slotIndex, exerciseCount))
  }

  const allTargetsMet = Array.from({ length: totalSets }, (_, i) => i).every((i) => {
    const log = exercise.set_logs.find((l) => l.set_number === i + 1)
    return log !== undefined && log.completed_reps >= targetRepsForSet(exercise, i)
  })
  const showVideo = phase === 'intro' || phase === 'countdown' || phase === 'active'

  return (
    <div className="screen timed">
      <header className="timed__bar">
        <button className="timed__back" onClick={() => navigate('/')} aria-label="Back to dashboard">
          <Icon name="chevronLeft" size={22} />
        </button>
        <span className="timed__bar-title">{exercise.name}</span>
        <span className="timed__bar-set">
          {phase !== 'done' && phase !== 'difficulty' && totalSets > 1 ? `Set ${setIdx + 1}/${totalSets}` : ''}
        </span>
      </header>

      {showVideo && <VideoPlayer videoUrl={exercise.video_url} />}

      {phase === 'intro' && (
        <>
          <div className="timed__card timed__target">
            <span className="timed__badge">
              <Icon name="timer" size={26} />
            </span>
            <div>
              <h1 className="timed__name">{exercise.name}</h1>
              <div className="timed__muted">Target</div>
              <div className="timed__target-value">
                <Icon name="clock" size={18} />
                {target} seconds
                {totalSets > 1 && <span className="timed__muted"> · {totalSets} sets</span>}
              </div>
            </div>
          </div>
          <div className="timed__card timed__tip">
            <Icon name="lightbulb" size={22} />
            <div>
              <div className="timed__tip-title">Tip</div>
              <div className="timed__muted">{exercise.note || DEFAULT_TIP}</div>
            </div>
          </div>
          <button className="btn-primary timed__cta" onClick={() => {
              unlockTickSound()
              setPhase('countdown')
            }}>
            <Icon name="play" size={18} />
            Start Exercise
          </button>
        </>
      )}

      {phase === 'countdown' && (
        <div className="timed__center">
          <CircularCountdown secondsLeft={secondsLeft} totalSeconds={GET_READY_SECONDS} size={150} stroke={10} />
          <h2 className="timed__heading">Get ready…</h2>
          <p className="timed__muted">
            Starting in {secondsLeft} second{secondsLeft === 1 ? '' : 's'}
          </p>
          <div className="timed__wave" aria-hidden>
            {Array.from({ length: 9 }, (_, i) => (
              <span key={i} style={{ animationDelay: `${i * 0.09}s` }} />
            ))}
          </div>
        </div>
      )}

      {phase === 'active' && (
        <div className="timed__center">
          <CircularCountdown secondsLeft={secondsLeft} totalSeconds={target} size={200} stroke={14}>
            <span className="timed__clock">{formatClock(secondsLeft)}</span>
            <span className="timed__muted">{paused ? 'Paused' : 'Remaining'}</span>
          </CircularCountdown>
          {secondsLeft <= target / 2 && secondsLeft > 0 && (
            <span className="timed__chip">
              <Icon name="activity" size={16} />
              Halfway there!
            </span>
          )}
          <div className="timed__controls">
            <button className="btn-secondary" onClick={() => {
                unlockTickSound()
                setPaused((p) => !p)
              }}>
              <Icon name={paused ? 'play' : 'pause'} size={18} />
              {paused ? 'Resume' : 'Pause'}
            </button>
            <button className="btn-primary" onClick={endEarly}>
              <Icon name="stop" size={18} />
              End
            </button>
          </div>
        </div>
      )}

      {phase === 'rest' && (
        <div className="timed__center">
          <span className="timed__badge timed__badge--lg">
            <Icon name="hourglass" size={30} />
          </span>
          <h2 className="timed__heading">Rest</h2>
          <span className="timed__clock timed__clock--lg">{formatClock(secondsLeft)}</span>
          <span className="timed__muted">Remaining</span>
          <div className="timed__progress" aria-hidden>
            <span style={{ width: `${(1 - msLeft / (REST_BETWEEN_SETS_SECONDS * 1000)) * 100}%` }} />
          </div>
          <div className="timed__card timed__tip">
            <Icon name="wind" size={22} />
            <div className="timed__muted">
              Catch your breath.
              <br />
              Next: <strong>{exercise.name}</strong> (Set {setIdx + 2} of {totalSets})
            </div>
          </div>
          <button className="btn-secondary timed__cta" onClick={() => setPhase('next-set')}>
            Skip Rest
          </button>
        </div>
      )}

      {phase === 'next-set' && (
        <div className="timed__card timed__next">
          <span className="timed__done-check timed__done-check--sm">
            <Icon name="check" size={22} />
          </span>
          <h2 className="timed__heading">Set {setIdx + 1} Complete!</h2>
          <p className="timed__score">
            {lastHeld} / {target} sec
          </p>
          <p className="timed__muted">
            Next: Set {setIdx + 2} of {totalSets} · {targetRepsForSet(exercise, setIdx + 1)} seconds
          </p>
          <button className="btn-primary timed__cta" onClick={startNextSet}>
            <Icon name="play" size={18} />
            Start Set {setIdx + 2}
          </button>
        </div>
      )}

      {phase === 'done' && (
        <div className="timed__center timed__done">
          <span className="timed__done-check">
            <Icon name="check" size={44} />
          </span>
          <h2 className="timed__title">Great Job!</h2>
          <p className="timed__muted">You held the {exercise.name.toLowerCase()} for</p>
          <p className="timed__score">
            {lastHeld} / {targetRepsForSet(exercise, totalSets - 1)} sec
          </p>
          {allTargetsMet && (
            <span className="timed__chip">
              <Icon name="star" size={16} />
              Perfect hold!
            </span>
          )}
          <button className="btn-primary timed__cta" onClick={() => setPhase('difficulty')}>
            Next
            <Icon name="chevronRight" size={18} />
          </button>
        </div>
      )}

      {phase === 'difficulty' && (
        <div className="timed__center">
          <h2 className="timed__heading">How difficult was that exercise?</h2>
          <div className="timed__faces" role="radiogroup" aria-label="Difficulty">
            {DIFFICULTIES.map((d) => (
              <button
                key={d.rpe}
                role="radio"
                aria-checked={difficulty === d.rpe}
                className={`timed__face${difficulty === d.rpe ? ' timed__face--selected' : ''}`}
                onClick={() => setDifficulty(d.rpe)}
              >
                <Face kind={d.face} />
                <span>{d.label}</span>
              </button>
            ))}
          </div>
          <p className="timed__muted">Your feedback helps your coach adjust your plan.</p>
          <button className="btn-primary timed__cta" onClick={finishExercise}>
            Next
            <Icon name="chevronRight" size={18} />
          </button>
        </div>
      )}
    </div>
  )
}

function Face({ kind }: { kind: 'easy' | 'moderate' | 'hard' }) {
  const mouth =
    kind === 'easy' ? 'M8 14c1 2 2.4 3 4 3s3-1 4-3' : kind === 'moderate' ? 'M8.5 14.5c1 1.2 2.2 1.8 3.5 1.8s2.5-.6 3.5-1.8' : 'M8.5 16.5c1-1.4 2.2-2 3.5-2s2.5.6 3.5 2'
  return (
    <svg viewBox="0 0 24 24" width="34" height="34" aria-hidden>
      <circle cx="12" cy="12" r="10" fill="currentColor" opacity=".9" />
      <circle cx="9" cy="10" r="1.2" fill="#3a2a10" />
      <circle cx="15" cy="10" r="1.2" fill="#3a2a10" />
      <path d={mouth} stroke="#3a2a10" strokeWidth="1.6" fill="none" strokeLinecap="round" />
    </svg>
  )
}

// Keeps the phone screen on while a timer runs (where the browser supports
// it). The lock drops when the page is hidden, so it's re-taken on return.
function useWakeLock(enabled: boolean) {
  useEffect(() => {
    if (!enabled || !('wakeLock' in navigator)) return
    let lock: WakeLockSentinel | null = null
    let cancelled = false
    const acquire = () => {
      if (document.visibilityState !== 'visible') return
      navigator.wakeLock
        .request('screen')
        .then((l) => {
          if (cancelled) void l.release()
          else lock = l
        })
        .catch(() => {
          // e.g. battery saver — the timer still works, the screen may dim
        })
    }
    acquire()
    document.addEventListener('visibilitychange', acquire)
    return () => {
      cancelled = true
      document.removeEventListener('visibilitychange', acquire)
      void lock?.release()
    }
  }, [enabled])
}
