import { Suspense, useState } from 'react'
import { Link } from 'react-router-dom'
import type { DashboardWorkout } from '../types'
import { appTodayIso, formatDayDate, formatMinutes } from '../utils'
import { levelForPoints, stageName, XP_PER_WORKOUT } from '../plant3d/levels'
import { LazyPlantCanvas, StageProgress } from './Garden'
import { Icon } from './Icon'

const ILLUSTRATIONS = {
  strength: '/illustrations/strength.webp',
  cardio: '/illustrations/cardio.webp',
} as const

/** "12 min": how long a workout takes — the cardio circuit's estimate, else her usual session length. */
export function workoutLength(workout: DashboardWorkout, sessionMinutes: number | null): string | null {
  if (workout.cardio) return formatMinutes(workout.cardio.estimated_seconds)
  return sessionMinutes ? `${sessionMinutes} min` : null
}

/** "Today", "Tomorrow" or "Thu 26 Nov". */
export function relativeDay(isoDate: string): string {
  const today = appTodayIso()
  if (isoDate === today) return 'Today'
  const [y, m, d] = today.split('-').map(Number)
  const tomorrow = new Date(Date.UTC(y, m - 1, d + 1)).toISOString().slice(0, 10)
  return isoDate === tomorrow ? 'Tomorrow' : formatDayDate(isoDate)
}

function displayName(workout: DashboardWorkout): string {
  return workout.kind === 'cardio' ? 'Cardio' : workout.name
}

/** The round coloured icon: a heart for cardio, a dumbbell for strength. */
export function WorkoutBadge({ workout, size = 'lg' }: { workout: DashboardWorkout; size?: 'lg' | 'sm' }) {
  const cardio = workout.kind === 'cardio'
  return (
    <span className={`workout-badge workout-badge--${cardio ? 'cardio' : 'strength'} workout-badge--${size}`}>
      <Icon name={cardio ? 'heart' : 'dumbbell'} size={size === 'lg' ? 30 : 26} />
    </span>
  )
}

interface TodayCardProps {
  // Today's workout, or on a rest day the next scheduled one (undefined when none is left).
  workout: DashboardWorkout | undefined
  isToday: boolean
  weekNumber: number
  sessionMinutes: number | null
  coachNotes: string | null
  onStart: () => void
}

/** The hero card: start / continue today's workout, today's finished one, or the rest day. */
export function TodayCard({ workout, isToday, weekNumber, sessionMinutes, coachNotes, onStart }: TodayCardProps) {
  const [notesOpen, setNotesOpen] = useState(false)
  const done = isToday && workout?.status === 'completed'
  const rest = !isToday
  const kind = workout?.kind === 'cardio' ? 'cardio' : 'strength'
  const length = workout ? workoutLength(workout, sessionMinutes) : null

  const label = rest ? 'Today' : done ? 'Done for Today' : "Today's Workout"
  let title: string
  let meta: string | null
  if (!workout) {
    title = 'Rest Day'
    meta = 'No more workouts this week'
  } else if (rest) {
    title = 'Rest Day'
    meta = `Next: ${displayName(workout)} · ${relativeDay(workout.date)}`
  } else {
    title = displayName(workout)
    meta = done && workout.duration_seconds != null ? `Took ${formatMinutes(workout.duration_seconds)}` : length
  }

  return (
    <section className={`today-hero today-hero--${rest ? 'rest' : kind}${done ? ' today-hero--done' : ''}`}>
      <span className="today-hero__label">
        <Icon name={done ? 'check' : 'calendar'} size={18} />
        {label}
      </span>
      <div className="today-hero__body">
        {rest || !workout ? (
          <span className="workout-badge workout-badge--rest workout-badge--lg">
            <Icon name="leaf" size={30} />
          </span>
        ) : done ? (
          <span className="workout-badge workout-badge--done workout-badge--lg">
            <Icon name="check" size={30} />
          </span>
        ) : (
          <WorkoutBadge workout={workout} />
        )}
        <div className="today-hero__text">
          <h2 className="today-hero__title">{title}</h2>
          {meta && (
            <span className="today-hero__meta">
              <Icon name={rest ? 'calendar' : 'clock'} size={18} />
              {meta}
            </span>
          )}
          <span className="today-hero__chip">
            <Icon name="leaf" size={13} />
            Week {weekNumber}
          </span>
        </div>
        {!rest && workout && (
          <img className={`today-hero__art today-hero__art--${kind}`} src={ILLUSTRATIONS[kind]} alt="" />
        )}
      </div>

      {coachNotes && (
        <button
          type="button"
          className={`today-hero__note${notesOpen ? ' today-hero__note--open' : ''}`}
          onClick={() => setNotesOpen((open) => !open)}
          aria-expanded={notesOpen}
        >
          <Icon name="chat" size={16} />
          <span>
            <strong>Coach:</strong> {coachNotes}
          </span>
        </button>
      )}

      {workout && !rest && !done && workout.can_start ? (
        <button className="today-hero__action" onClick={onStart}>
          {workout.started_at ? 'Continue Workout' : 'Start Workout'}
          <Icon name="arrowRight" size={20} />
        </button>
      ) : (
        workout && (
          <Link className="today-hero__action today-hero__action--secondary" to={`/workout/${workout.session_id}`}>
            View {done ? 'Workout' : rest ? 'Next Workout' : 'Workout'}
            <Icon name="arrowRight" size={20} />
          </Link>
        )
      )}
    </section>
  )
}

interface GardenCardProps {
  xp: number
  userId: string
  onOpen: () => void
}

/** "Your Garden": a small 3D plant, its stage, XP and progress, and View Garden. */
export function GardenCard({ xp, userId, onOpen }: GardenCardProps) {
  const { level } = levelForPoints(xp)
  return (
    <section className="garden-card">
      <button type="button" className="garden-card__plant" onClick={onOpen} aria-label="View your garden">
        <Suspense fallback={null}>
          <LazyPlantCanvas step={level} userId={userId} className="plant-canvas plant-canvas--card" />
        </Suspense>
      </button>
      <div className="garden-card__info">
        <span className="garden-card__label">
          <Icon name="leaf" size={18} />
          Your Garden
        </span>
        <span className="garden-card__stage">{stageName(level)}</span>
        <span className="garden-card__xp">
          <Icon name="trophy" size={18} />
          {xp} XP
        </span>
        <StageProgress xp={xp} />
        <span className="garden-card__tip">⭐ +{XP_PER_WORKOUT} XP per workout</span>
      </div>
      <button type="button" className="garden-card__view" onClick={onOpen}>
        View Garden <Icon name="arrowRight" size={14} />
      </button>
    </section>
  )
}

interface WorkoutRowProps {
  workout: DashboardWorkout
  sessionMinutes: number | null
}

/** One workout in a list: when, what, how long, and View. */
export function WorkoutRow({ workout, sessionMinutes }: WorkoutRowProps) {
  const { status } = workout
  const length =
    status === 'completed' && workout.duration_seconds != null
      ? formatMinutes(workout.duration_seconds)
      : status === 'scheduled'
        ? workoutLength(workout, sessionMinutes)
        : null
  return (
    <div className="card workout-row">
      <span className="workout-row__when">
        <Icon name="calendar" size={18} />
        {relativeDay(workout.date)}
        {status !== 'scheduled' && (
          <span className={`workout-row__status workout-row__status--${status}`}>
            {status === 'completed' && <Icon name="check" size={12} />}
            {status === 'completed' ? 'Completed' : 'Missed'}
          </span>
        )}
      </span>
      <div className="workout-row__body">
        <WorkoutBadge workout={workout} size="sm" />
        <div className="workout-row__text">
          <span className="workout-row__name">{displayName(workout)}</span>
          {length && (
            <span className="workout-row__meta">
              <Icon name="clock" size={15} />
              {length}
            </span>
          )}
        </div>
        <Link className="workout-row__view" to={`/workout/${workout.session_id}`}>
          View
        </Link>
      </div>
    </div>
  )
}
