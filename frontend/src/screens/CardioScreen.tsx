import { useEffect, useMemo, useRef, useState } from 'react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { CircularCountdown } from '../components/CircularCountdown'
import { Icon } from '../components/Icon'
import { useAppState } from '../state/AppStateContext'
import { useCountdown } from '../state/useCountdown'
import { useWakeLock } from '../state/useWakeLock'
import { playTick, unlockTickSound } from '../state/tickSound'
import { formatClock } from '../utils'
import type { CardioExercise, CardioPlan } from '../types'

// The circuit as a flat list of timed steps: get ready, then every exercise
// of every round, with a rest after each one — a longer round rest after a
// round's last exercise — and nothing after the very last.
type Step =
  | { kind: 'ready'; seconds: number; exercise: number }
  | { kind: 'work'; seconds: number; round: number; exercise: number }
  | { kind: 'rest'; seconds: number; round: number; exercise: number }
  | { kind: 'round-rest'; seconds: number; round: number; exercise: number }

// `round` is 1-based; `exercise` indexes the circuit — for a rest, the
// exercise coming up next (whose clip is already loaded and shown).
function buildSteps(plan: CardioPlan): Step[] {
  const count = plan.exercises.length
  const steps: Step[] = [{ kind: 'ready', seconds: plan.get_ready_seconds, exercise: 0 }]
  for (let round = 1; round <= plan.rounds; round++) {
    for (let exercise = 0; exercise < count; exercise++) {
      steps.push({ kind: 'work', seconds: plan.work_seconds, round, exercise })
      const lastOfRound = exercise === count - 1
      if (lastOfRound && round === plan.rounds) continue
      steps.push(
        lastOfRound
          ? { kind: 'round-rest', seconds: plan.round_rest_seconds, round: round + 1, exercise: 0 }
          : { kind: 'rest', seconds: plan.exercise_rest_seconds, round, exercise: exercise + 1 },
      )
    }
  }
  return steps
}

// A cardio day (sessions.kind = 'cardio'): one continuous, follow-along
// circuit. A 10 s get-ready, then each exercise's clip plays (muted, looped)
// under a seconds-left ring; a 20 s rest shows the next one, and a 30 s
// rest separates rounds. At the end she rates how it felt
// (CardioRatingScreen), which sets next week's level. Nothing is logged on
// the way, so leaving and coming back starts the circuit over.
export function CardioScreen() {
  const { dashboard } = useAppState()
  const navigate = useNavigate()
  const { dayNumber } = useParams()
  const dayNum = Number(dayNumber)
  const day = dashboard?.days.find((d) => d.day_number === dayNum)
  const plan = day?.kind === 'cardio' ? day.cardio : undefined

  const steps = useMemo(() => (plan ? buildSteps(plan) : []), [plan])
  const [stepIdx, setStepIdx] = useState(0)
  const [paused, setPaused] = useState(false)
  const step = steps[stepIdx] as Step | undefined
  const running = step !== undefined && !paused

  const msLeft = useCountdown(step?.seconds ?? 0, running, advance, stepIdx)
  const secondsLeft = Math.ceil(msLeft / 1000)

  useWakeLock(step !== undefined)

  // A tick on each of the last three seconds of every countdown.
  useEffect(() => {
    if (running && secondsLeft > 0 && secondsLeft <= 3) playTick()
  }, [running, secondsLeft])

  function advance() {
    if (step?.kind === 'work') navigator.vibrate?.(200)
    if (stepIdx + 1 >= steps.length) {
      navigate(`/day/${dayNum}/cardio/rate`, { replace: true })
      return
    }
    setStepIdx(stepIdx + 1)
  }

  function skip() {
    unlockTickSound()
    setPaused(false)
    advance()
  }

  function togglePause() {
    unlockTickSound()
    setPaused((p) => !p)
  }

  if (!day || !plan || day.locked || day.status === 'missed' || plan.exercises.length === 0) {
    return <Navigate to="/" replace />
  }

  if (!step) return null
  const exercise = plan.exercises[step.exercise]
  const count = plan.exercises.length
  const upNext = step.kind === 'work' ? nextExerciseName(steps, stepIdx, plan.exercises) : null

  return (
    <div className="screen timed cardio">
      <header className="timed__bar">
        <button className="timed__back" onClick={() => navigate('/')} aria-label="Back to dashboard">
          <Icon name="chevronLeft" size={22} />
        </button>
        <span className="timed__bar-title">Cardio</span>
        <span className="timed__bar-set">
          {step.kind !== 'ready' && plan.rounds > 1 ? `Round ${'round' in step ? step.round : 1}/${plan.rounds}` : ''}
        </span>
      </header>

      <CardioVideo exercise={exercise} playing={step.kind === 'work' && !paused} />

      {step.kind === 'ready' && (
        <div className="timed__center">
          <CircularCountdown secondsLeft={secondsLeft} totalSeconds={step.seconds} size={150} stroke={10} />
          <h2 className="timed__heading">Get ready…</h2>
          <p className="timed__muted">
            First up: <strong>{exercise.name}</strong>
          </p>
          <p className="timed__muted cardio__plan">
            {count} exercises · {plan.work_seconds} s each
            {plan.rounds > 1 ? ` · ${plan.rounds} rounds` : ''}
          </p>
        </div>
      )}

      {step.kind === 'work' && (
        <div className="timed__center">
          <div className="cardio__now">
            <span className="timed__muted">
              Exercise {step.exercise + 1} of {count}
            </span>
            <h1 className="timed__name">{exercise.name}</h1>
          </div>
          <CircularCountdown secondsLeft={secondsLeft} totalSeconds={step.seconds} size={180} stroke={12}>
            <span className="timed__clock">{formatClock(secondsLeft)}</span>
            <span className="timed__muted">{paused ? 'Paused' : 'Remaining'}</span>
          </CircularCountdown>
          <div className="timed__controls">
            <button className="btn-secondary" onClick={togglePause}>
              <Icon name={paused ? 'play' : 'pause'} size={18} />
              {paused ? 'Resume' : 'Pause'}
            </button>
          </div>
          {upNext && <p className="timed__muted">Up next: {upNext}</p>}
        </div>
      )}

      {(step.kind === 'rest' || step.kind === 'round-rest') && (
        <div className="timed__center">
          <span className="timed__badge timed__badge--lg">
            <Icon name={step.kind === 'round-rest' ? 'repeat' : 'hourglass'} size={30} />
          </span>
          <h2 className="timed__heading">
            {step.kind === 'round-rest' ? `Round ${step.round - 1} complete!` : 'Rest'}
          </h2>
          <span className="timed__clock timed__clock--lg">{formatClock(secondsLeft)}</span>
          <span className="timed__muted">{paused ? 'Paused' : 'Remaining'}</span>
          <div className="timed__progress" aria-hidden>
            <span style={{ width: `${(1 - msLeft / (step.seconds * 1000)) * 100}%` }} />
          </div>
          <div className="timed__card timed__tip">
            <Icon name="wind" size={22} />
            <div className="timed__muted">
              Catch your breath.
              <br />
              {step.kind === 'round-rest' ? `Round ${step.round} starts with ` : 'Next: '}
              <strong>{exercise.name}</strong>
            </div>
          </div>
          <div className="timed__controls">
            <button className="btn-secondary" onClick={togglePause}>
              <Icon name={paused ? 'play' : 'pause'} size={18} />
              {paused ? 'Resume' : 'Pause'}
            </button>
            <button className="btn-primary" onClick={skip}>
              Skip Rest
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function nextExerciseName(steps: Step[], stepIdx: number, exercises: CardioExercise[]): string | null {
  const next = steps.slice(stepIdx + 1).find((s) => s.kind === 'work')
  return next ? exercises[next.exercise].name : null
}

// The current (or, during a rest, the next) exercise's clip. It loads as
// soon as it's shown, so a rest doubles as buffering time, and plays —
// muted, so the browser allows it without a tap, and looped, since the
// countdown, not the clip, decides when the exercise ends — only while
// that exercise is on. Keyed by exercise, so each clip starts from the top.
function CardioVideo({ exercise, playing }: { exercise: CardioExercise; playing: boolean }) {
  const ref = useRef<HTMLVideoElement>(null)

  useEffect(() => {
    const video = ref.current
    if (!video) return
    video.muted = true
    if (playing) {
      video.play().catch(() => {
        // e.g. Low Power Mode blocking autoplay — the timer still runs
      })
    } else {
      video.pause()
    }
  }, [playing, exercise.id])

  return (
    <div className="cardio__video">
      {exercise.video_url ? (
        <video
          key={exercise.id}
          ref={ref}
          src={exercise.video_url}
          poster={exercise.poster_url ?? undefined}
          muted
          loop
          playsInline
          preload="auto"
          disablePictureInPicture
        />
      ) : (
        <img src={exercise.poster_url ?? '/exercise-placeholder.jpg'} alt="" />
      )}
    </div>
  )
}
