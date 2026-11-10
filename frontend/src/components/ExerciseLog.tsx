import { Icon } from './Icon'
import { LEVELS, levelForCardioRating, levelIndexForRpe } from './effortLevels'
import { formatMinutes, repUnit, targetRepsForSet } from '../utils'
import type { CardioPlan, ExerciseEntry } from '../types'

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

// A cardio workout's level (and, once done, how it felt), then the circuit
// it runs — shown in place of the exercise list for a cardio session.
export function CardioDetails({ cardio, completed }: { cardio: CardioPlan; completed: boolean }) {
  const felt = levelForCardioRating(cardio.rating)
  return (
    <>
      <div className="card cardio-detail__summary">
        <div className="cardio-detail__level">
          <Icon name="heart" size={20} />
          <span>
            {cardio.rounds} round{cardio.rounds === 1 ? '' : 's'} · {cardio.work_seconds} s per exercise · about{' '}
            {formatMinutes(cardio.estimated_seconds)}
          </span>
        </div>
        {cardio.is_period && (
          <div className="workout-detail__note">
            Lighter today — planned {cardio.planned_work_seconds} s per exercise
          </div>
        )}
        <div className="workout-detail__muted">
          {cardio.exercise_rest_seconds} s rest between exercises
          {cardio.rounds > 1 ? `, ${cardio.round_rest_seconds} s between rounds` : ''}
        </div>
        {completed && (
          <div className="workout-detail__effort">
            {felt ? (
              <>
                <span className={`effort-dot effort-dot--${LEVELS.indexOf(felt)}`} />
                Felt: {felt.label}
              </>
            ) : (
              'Felt: Not rated'
            )}
          </div>
        )}
      </div>
      <div className="workout-detail__list">
        {cardio.exercises.map((exercise, i) => (
          <div key={exercise.id} className="card workout-detail__exercise">
            <div className="workout-detail__row">
              <div className="workout-detail__thumb">
                <img src={exercise.poster_url ?? '/exercise-placeholder.jpg'} alt="" loading="lazy" />
                <span className="workout-detail__number workout-detail__number--primary">{i + 1}</span>
              </div>
              <div className="workout-detail__info">
                <div className="workout-detail__name">{exercise.name}</div>
                <div className="workout-detail__muted">{cardio.work_seconds} seconds</div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </>
  )
}
