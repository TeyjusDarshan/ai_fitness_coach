import { LEVELS, levelIndexForRpe } from './EffortSlider'
import { repUnit, targetRepsForSet } from '../utils'
import type { ExerciseEntry } from '../types'

// What was prescribed for one exercise, and what was logged against it set
// by set (seconds for a timed exercise). Shared by the client's workout
// detail screen and the coach's client monitor.

function setNumbers(exercise: ExerciseEntry): number[] {
  return Array.from({ length: exercise.sets ?? 0 }, (_, i) => i + 1)
}

export function Prescription({ exercise }: { exercise: ExerciseEntry }) {
  const targets = setNumbers(exercise).map((n) => targetRepsForSet(exercise, n - 1))
  const uniform = targets.every((reps) => reps === targets[0])
  return (
    <>
      <div className="workout-detail__muted">
        {exercise.sets ?? 0} sets × {uniform ? targets[0] : targets.join(', ')} {repUnit(exercise)}
      </div>
      {exercise.note && <div className="workout-detail__note">{exercise.note}</div>}
    </>
  )
}

export function LoggedSets({ exercise }: { exercise: ExerciseEntry }) {
  return (
    <div className="workout-detail__sets">
      {setNumbers(exercise).map((n) => {
        const log = exercise.set_logs.find((l) => l.set_number === n)
        return (
          <div key={n} className="workout-detail__set">
            <span>Set {n}</span>
            <span>
              <strong>{log ? log.completed_reps : '—'}</strong> / {targetRepsForSet(exercise, n - 1)} {repUnit(exercise)}
            </span>
          </div>
        )
      })}
      <div className="workout-detail__effort">
        {exercise.rpe_logged === false ? (
          'Effort: Not rated'
        ) : (
          <>
            <span className={`effort-dot effort-dot--${levelIndexForRpe(exercise.rpe)}`} />
            Effort: {LEVELS[levelIndexForRpe(exercise.rpe)].label}
          </>
        )}
      </div>
    </div>
  )
}
