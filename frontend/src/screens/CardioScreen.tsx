import { useEffect, useMemo, useRef, useState } from 'react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { CircularCountdown } from '../components/CircularCountdown'
import { Icon } from '../components/Icon'
import { logCardioStep } from '../api'
import { useAppState } from '../state/AppStateContext'
import { useCountdown } from '../state/useCountdown'
import { useWakeLock } from '../state/useWakeLock'
import { playTick, unlockTickSound } from '../state/tickSound'
import { formatClock, formatShortClock } from '../utils'
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
// under a seconds-left ring; a rest a third as long shows the next one, and
// a 30 s rest separates rounds. At the end she rates how it felt
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
  const [showInfo, setShowInfo] = useState(false)
  const step = steps[stepIdx] as Step | undefined
  const running = step !== undefined && !paused

  // Time this step has spent paused: what's banked, plus the pause under
  // way (if any). Reset as each step starts.
  const pausedMs = useRef(0)
  const pausedSince = useRef<number | null>(null)

  const msLeft = useCountdown(step?.seconds ?? 0, running, () => finishStep(false), stepIdx)
  const secondsLeft = Math.ceil(msLeft / 1000)

  useWakeLock(step !== undefined)

  // A tick on each of the last three seconds of every countdown.
  useEffect(() => {
    if (running && secondsLeft > 0 && secondsLeft <= 3) playTick()
  }, [running, secondsLeft])

  // The current step is over — run out, or skipped. Record how it went
  // (fire-and-forget, like set logs: a lost one only leaves a gap in the
  // history), then move on.
  function finishStep(skipped: boolean) {
    if (!step) return
    const now = Date.now()
    const pausedTotal = pausedMs.current + (pausedSince.current === null ? 0 : now - pausedSince.current)
    pausedMs.current = 0
    pausedSince.current = null

    const target = stepLogTarget(step, plan?.exercises.length ?? 0)
    if (target && day?.session_id) {
      logCardioStep(day.session_id, {
        ...target,
        actual_seconds: skipped ? Math.max(0, Math.round(step.seconds - msLeft / 1000)) : step.seconds,
        paused_seconds: Math.round(pausedTotal / 1000),
        skipped,
      }).catch(() => {})
    }

    if (step.kind === 'work') navigator.vibrate?.(200)
    if (stepIdx + 1 >= steps.length) {
      navigate(`/day/${dayNum}/cardio/rate`, { replace: true })
      return
    }
    setStepIdx(stepIdx + 1)
  }

  function skip() {
    unlockTickSound()
    setPaused(false)
    finishStep(true)
  }

  function togglePause() {
    unlockTickSound()
    if (paused) {
      if (pausedSince.current !== null) pausedMs.current += Date.now() - pausedSince.current
      pausedSince.current = null
    } else {
      pausedSince.current = Date.now()
    }
    setPaused(!paused)
  }

  if (!day || !plan || day.locked || day.status === 'missed' || plan.exercises.length === 0) {
    return <Navigate to="/" replace />
  }

  if (!step) return null
  const exercise = plan.exercises[step.exercise]
  const count = plan.exercises.length

  return (
    <div className="screen timed cardio">
      <header className="timed__bar">
        <button className="timed__back" onClick={() => navigate('/')} aria-label="Back to dashboard">
          <Icon name="chevronLeft" size={22} />
        </button>
        <span className="timed__bar-title">Cardio</span>
        <button
          className="timed__back cardio__info-button"
          onClick={() => setShowInfo((open) => !open)}
          aria-label="About this workout"
          aria-expanded={showInfo}
        >
          <Icon name="info" size={26} />
        </button>
      </header>

      {showInfo && (
        <div className="timed__card cardio__info">
          <div>
            <strong>Today&apos;s circuit</strong>
            <div className="timed__muted">
              {count} exercises · {plan.work_seconds} s each · {plan.exercise_rest_seconds} s rest between them
            </div>
            <div className="timed__muted">
              {plan.rounds} round{plan.rounds === 1 ? '' : 's'}
              {plan.rounds > 1 ? ` · ${plan.round_rest_seconds} s rest between rounds` : ''}
              {plan.is_period ? ' · lighter today' : ''}
            </div>
          </div>
        </div>
      )}

      <CardioVideo
        exercise={exercise}
        playing={step.kind === 'work' && !paused}
        // During an exercise, the time left; before one, how long it will run.
        badge={formatShortClock(step.kind === 'work' ? secondsLeft : plan.work_seconds)}
      />

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
        <div className="timed__center cardio__work">
          <div className="timed__card cardio__now">
            <span className="timed__muted">
              Exercise {step.exercise + 1} of {count}
            </span>
            <h1 className="timed__name">{exercise.name}</h1>
          </div>
          <CircularCountdown secondsLeft={secondsLeft} totalSeconds={step.seconds} size={190} stroke={13}>
            <span className="timed__clock timed__clock--lg">{formatClock(secondsLeft)}</span>
            <span className="timed__muted">{paused ? 'Paused' : 'Remaining'}</span>
          </CircularCountdown>
          <div className="timed__card timed__tip cardio__tip">
            <Icon name="heart" size={26} />
            <div className="timed__muted">
              <strong className="cardio__tip-title">Tip:</strong> {WORK_TIPS[step.exercise % WORK_TIPS.length]}
            </div>
          </div>
          <div className="timed__controls">
            <button className="btn-secondary" onClick={togglePause}>
              <Icon name={paused ? 'play' : 'pause'} size={18} />
              {paused ? 'Resume' : 'Pause'}
            </button>
            <button className="btn-primary" onClick={skip}>
              <Icon name="skipForward" size={20} />
              Skip Exercise
            </button>
          </div>
          <CircuitProgress current={step.exercise} count={count} />
        </div>
      )}

      {(step.kind === 'rest' || step.kind === 'round-rest') && (
        <div className="timed__center cardio__rest">
          <span className="timed__badge timed__badge--lg">
            <Icon name={step.kind === 'round-rest' ? 'repeat' : 'hourglass'} size={30} />
          </span>
          <h2 className="timed__heading">
            {step.kind === 'round-rest' ? `Round ${step.round - 1} complete!` : 'Rest'}
          </h2>
          {step.kind === 'rest' && plan.rounds > 1 && (
            <span className="timed__muted">
              Round {step.round} of {plan.rounds}
            </span>
          )}
          <CircularCountdown secondsLeft={secondsLeft} totalSeconds={step.seconds} size={190} stroke={13}>
            <span className="timed__clock timed__clock--lg">{formatClock(secondsLeft)}</span>
            <span className="timed__muted">{paused ? 'Paused' : 'Remaining'}</span>
          </CircularCountdown>

          <div className="timed__card cardio__next">
            <img
              className="cardio__next-thumb"
              src={exercise.poster_url ?? '/exercise-placeholder.jpg'}
              alt=""
            />
            <div className="cardio__next-text">
              <span className="cardio__next-label">
                {step.kind === 'round-rest' ? `Up next · Round ${step.round}` : 'Up next'}
              </span>
              <span className="cardio__next-name">{exercise.name}</span>
              <span className="timed__muted">
                {plan.work_seconds} seconds · {step.exercise + 1} of {count}
              </span>
            </div>
          </div>

          <div className="timed__card timed__tip cardio__tip">
            <Icon name="lightbulb" size={26} />
            <div className="timed__muted">
              <strong className="cardio__tip-title">Tip:</strong>{' '}
              {step.kind === 'round-rest' ? ROUND_REST_TIP : REST_TIPS[stepIdx % REST_TIPS.length]}
            </div>
          </div>

          <div className="timed__controls">
            <button className="btn-secondary" onClick={togglePause}>
              <Icon name={paused ? 'play' : 'pause'} size={18} />
              {paused ? 'Resume' : 'Pause'}
            </button>
            <button className="btn-primary" onClick={skip}>
              <Icon name="skipForward" size={20} />
              Skip Rest
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// Which session_cardio_logs row (and which half of it) a step belongs to:
// an exercise is its own; a rest belongs to the exercise before it — for a
// round rest, the previous round's last one. The get-ready isn't logged.
function stepLogTarget(
  step: Step,
  count: number,
): { round: number; position: number; part: 'exercise' | 'rest' } | null {
  if (step.kind === 'work') return { round: step.round, position: step.exercise, part: 'exercise' }
  if (step.kind === 'rest') return { round: step.round, position: step.exercise - 1, part: 'rest' }
  if (step.kind === 'round-rest') return { round: step.round - 1, position: count - 1, part: 'rest' }
  return null
}

// One per exercise, in turn.
const WORK_TIPS = [
  'Keep a comfortable pace. You should be able to talk.',
  'Breathe steadily — never hold your breath.',
  'Move at your own speed. Smaller movements are fine.',
  'Keep your core gently tight and your back tall.',
]

// One per rest, in turn.
const REST_TIPS = [
  "Take slow, deep breaths. You're doing great!",
  'Shake out your arms and legs while you wait.',
  'Stand tall and relax your shoulders.',
  'Sip some water if you need it.',
]
const ROUND_REST_TIP = 'Great round! Breathe deeply and get ready to go again.'

// Where she is in the round: done exercises, this one, and those to come.
function CircuitProgress({ current, count }: { current: number; count: number }) {
  return (
    <div className="cardio__progress" aria-label={`Exercise ${current + 1} of ${count}`}>
      <span className="cardio__progress-count">
        {current + 1} / {count}
      </span>
      <span className="cardio__progress-dots" aria-hidden>
        {Array.from({ length: count }, (_, i) => (
          <span
            key={i}
            className={`cardio__dot${i < current ? ' cardio__dot--done' : i === current ? ' cardio__dot--current' : ''}`}
          />
        ))}
      </span>
    </div>
  )
}

// The current (or, during a rest, the next) exercise's clip. It loads as
// soon as it's shown, so a rest doubles as buffering time, and plays —
// muted, so the browser allows it without a tap, and looped, since the
// countdown, not the clip, decides when the exercise ends — only while
// that exercise is on. Keyed by exercise, so each clip starts from the top.
function CardioVideo({
  exercise,
  playing,
  badge,
}: {
  exercise: CardioExercise
  playing: boolean
  // e.g. "00:30" — shown over the clip while it waits to start.
  badge: string | null
}) {
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
      {badge && (
        <span className="cardio__video-badge">
          <Icon name="play" size={16} />
          {badge}
        </span>
      )}
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
