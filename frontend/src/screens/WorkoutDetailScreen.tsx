import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { LEVELS, levelIndexForRpe } from '../components/EffortSlider'
import { Icon } from '../components/Icon'
import { Illustration } from '../components/Illustration'
import { useAppState } from '../state/AppStateContext'
import { useStartWorkout } from '../state/useStartWorkout'
import { WORKOUT_STATUS_LABELS, targetRepsForSet, workoutDateLabel } from '../utils'
import { youtubeThumbnailUrl } from '../youtube'
import type { ExerciseEntry } from '../types'

// Read-only view of one workout panel: what's prescribed for a scheduled or
// missed workout, and what was logged set by set for a completed one.
export function WorkoutDetailScreen() {
  const { dashboard } = useAppState()
  const navigate = useNavigate()
  const { sessionId } = useParams()
  const { start, error } = useStartWorkout()

  if (!dashboard) return null
  const workout = dashboard.workouts.find((w) => w.session_id === Number(sessionId))
  if (!workout) return <Navigate to="/" replace />

  const completed = workout.status === 'completed'

  return (
    <div className="screen workout-detail">
      <button className="back-link" onClick={() => navigate('/')}>
        <Icon name="chevronLeft" size={18} />
        Back
      </button>
      <div className="workout-detail__hero">
        <div>
          <h1 className="screen-title workout-detail__title">{workout.name}</h1>
          <p className="workout-detail__meta">
            <Icon name="calendar" size={16} />
            {WORKOUT_STATUS_LABELS[workout.status]} · {workoutDateLabel(workout)}
          </p>
        </div>
        <Illustration className="workout-detail__art" />
      </div>
      {error && <div className="error-banner">{error}</div>}

      <div className="workout-detail__list">
        {workout.exercises.map((exercise, i) => (
          <div key={exercise.id} className="card workout-detail__exercise">
            <div className="workout-detail__row">
              <div className="workout-detail__thumb">
                <img src={youtubeThumbnailUrl(exercise.video_url) ?? '/exercise-placeholder.jpg'} alt="" />
                <span className={`workout-detail__number workout-detail__number--${exercise.category}`}>
                  {i + 1}
                </span>
              </div>
              <div className="workout-detail__info">
                <div className="workout-detail__name">{exercise.name}</div>
                <Prescription exercise={exercise} />
              </div>
            </div>
            {completed && <LoggedSets exercise={exercise} />}
          </div>
        ))}
      </div>

      {workout.can_start && (
        <button className="btn-primary" onClick={() => void start(workout)}>
          <Icon name="play" size={18} />
          {workout.started_at ? 'Continue Workout' : 'Start Workout'}
        </button>
      )}
    </div>
  )
}

function setNumbers(exercise: ExerciseEntry): number[] {
  return Array.from({ length: exercise.sets ?? 0 }, (_, i) => i + 1)
}

function Prescription({ exercise }: { exercise: ExerciseEntry }) {
  const targets = setNumbers(exercise).map((n) => targetRepsForSet(exercise, n - 1))
  const uniform = targets.every((reps) => reps === targets[0])
  return (
    <>
      <div className="workout-detail__muted">
        {exercise.sets ?? 0} sets × {uniform ? targets[0] : targets.join(', ')} reps
      </div>
      {exercise.note && <div className="workout-detail__note">{exercise.note}</div>}
    </>
  )
}

function LoggedSets({ exercise }: { exercise: ExerciseEntry }) {
  return (
    <div className="workout-detail__sets">
      {setNumbers(exercise).map((n) => {
        const log = exercise.set_logs.find((l) => l.set_number === n)
        return (
          <div key={n} className="workout-detail__set">
            <span>Set {n}</span>
            <span>
              <strong>{log ? log.completed_reps : '—'}</strong> / {targetRepsForSet(exercise, n - 1)} reps
            </span>
          </div>
        )
      })}
      <div className="workout-detail__effort">
        <span className={`effort-dot effort-dot--${levelIndexForRpe(exercise.rpe)}`} />
        Effort: {LEVELS[levelIndexForRpe(exercise.rpe)].label}
      </div>
    </div>
  )
}
