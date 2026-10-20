import { Link } from 'react-router-dom'
import type { DashboardWorkout } from '../types'
import { WORKOUT_STATUS_LABELS, formatDayDate, workoutDateLabel } from '../utils'

interface Props {
  workout: DashboardWorkout
  timerLabel: string | null
  onStart: () => void
}

export function WorkoutPanel({ workout, timerLabel, onStart }: Props) {
  const { status, is_next: isNext, can_start: canStart } = workout

  return (
    <div className={`card workout-panel workout-panel--${status}${isNext ? ' workout-panel--next' : ''}`}>
      <div className="workout-panel__header">
        <span className="workout-panel__name">{workout.name}</span>
        <span className={`workout-panel__status workout-panel__status--${status}`}>
          {status === 'completed' && <span aria-hidden>✓ </span>}
          {WORKOUT_STATUS_LABELS[status]}
        </span>
      </div>
      <div className="workout-panel__meta">
        <span>{workoutDateLabel(workout)}</span>
        {status === 'scheduled' && timerLabel && <span>Timer: {timerLabel}</span>}
      </div>
      <div className="workout-panel__actions">
        <Link className="workout-panel__view" to={`/workout/${workout.session_id}`}>
          View
        </Link>
        {canStart && (
          <button className="workout-panel__start" onClick={onStart}>
            {workout.started_at ? 'Continue' : 'Start'} <span aria-hidden>›</span>
          </button>
        )}
        {isNext && !canStart && (
          <span className="workout-panel__opens">Opens {formatDayDate(workout.date)}</span>
        )}
      </div>
    </div>
  )
}
