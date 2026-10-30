import { Link } from 'react-router-dom'
import type { DashboardWorkout, WorkoutStatus } from '../types'
import { WORKOUT_STATUS_LABELS, formatDayDate, formatMinutes, workoutDateLabel } from '../utils'
import { Icon, type IconName } from './Icon'

const STATUS_ICONS: Record<WorkoutStatus, IconName> = {
  completed: 'dumbbell',
  missed: 'activity',
  scheduled: 'calendar',
}

interface Props {
  workout: DashboardWorkout
  timerLabel: string | null
  onStart: () => void
}

export function WorkoutPanel({ workout, timerLabel, onStart }: Props) {
  const { status, is_next: isNext, can_start: canStart } = workout

  return (
    <div className={`card workout-panel workout-panel--${status}${isNext ? ' workout-panel--next' : ''}`}>
      <span className={`workout-panel__icon workout-panel__icon--${status}`}>
        <Icon name={STATUS_ICONS[status]} size={24} />
      </span>
      <div className="workout-panel__body">
        <div className="workout-panel__header">
          <span className="workout-panel__name">{workout.name}</span>
          <span className={`workout-panel__status workout-panel__status--${status}`}>
            {status === 'completed' && <Icon name="check" size={12} />}
            {WORKOUT_STATUS_LABELS[status]}
          </span>
        </div>
        <div className="workout-panel__meta">
          <span>{workoutDateLabel(workout)}</span>
          {status === 'scheduled' && timerLabel && <span>Timer: {timerLabel}</span>}
          {status === 'completed' && workout.duration_seconds != null && (
            <span>{formatMinutes(workout.duration_seconds)}</span>
          )}
        </div>
        <div className="workout-panel__actions">
          <Link className="workout-panel__view" to={`/workout/${workout.session_id}`}>
            View <Icon name="chevronRight" size={14} />
          </Link>
          {canStart && (
            <button className="workout-panel__start" onClick={onStart}>
              {workout.started_at ? 'Continue' : 'Start'} <Icon name="chevronRight" size={14} />
            </button>
          )}
          {isNext && !canStart && (
            <span className="workout-panel__opens">
              <Icon name="calendar" size={14} />
              Opens {formatDayDate(workout.date)}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
