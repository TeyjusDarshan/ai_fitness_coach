import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { LEVELS, levelIndexForRpe } from '../components/EffortSlider'
import { useAppState } from '../state/AppStateContext'
import { useStartWorkout } from '../state/useStartWorkout'
import { WORKOUT_STATUS_LABELS, targetRepsForSet, workoutDateLabel } from '../utils'
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
      <button className="btn-link workout-detail__back" onClick={() => navigate('/')}>
        ‹ Back
      </button>
      <h1 className="screen-title">{workout.name}</h1>
      <p className="workout-detail__meta">
        {WORKOUT_STATUS_LABELS[workout.status]} · {workoutDateLabel(workout)}
      </p>
      {error && <div className="error-banner">{error}</div>}

      <div className="workout-detail__list">
        {workout.exercises.map((exercise) => (
          <div key={exercise.id} className="card workout-detail__exercise">
            <div className="workout-detail__name">{exercise.name}</div>
            {completed ? <LoggedSets exercise={exercise} /> : <Prescription exercise={exercise} />}
          </div>
        ))}
      </div>

      {workout.can_start && (
        <button className="btn-primary" onClick={() => void start(workout)}>
          {workout.started_at ? 'Continue workout' : 'Start workout'}
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
      <div className="workout-detail__line">
        {exercise.sets ?? 0} sets × {uniform ? targets[0] : targets.join(', ')} reps
      </div>
      {exercise.rep_range && <div className="workout-detail__muted">Range {exercise.rep_range}</div>}
      {exercise.note && <div className="workout-detail__muted">{exercise.note}</div>}
    </>
  )
}

function LoggedSets({ exercise }: { exercise: ExerciseEntry }) {
  return (
    <>
      {setNumbers(exercise).map((n) => {
        const log = exercise.set_logs.find((l) => l.set_number === n)
        return (
          <div key={n} className="workout-detail__set">
            <span>Set {n}</span>
            <span>
              {log ? log.completed_reps : '—'} / {targetRepsForSet(exercise, n - 1)} reps
            </span>
          </div>
        )
      })}
      <div className="workout-detail__muted">Effort: {LEVELS[levelIndexForRpe(exercise.rpe)].label}</div>
    </>
  )
}
