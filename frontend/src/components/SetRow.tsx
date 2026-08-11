interface Props {
  index: number
  targetReps: string | null
  reps: number
  confirmed: boolean
  onChange: (reps: number) => void
  onConfirm: () => void
}

export function SetRow({ index, targetReps, reps, confirmed, onChange, onConfirm }: Props) {
  return (
    <div className="set-row">
      <span className="set-row__label">
        Set {index + 1}
        {targetReps ? <span className="set-row__target">Target {targetReps} reps</span> : null}
      </span>

      <div className="set-row__controls">
        <div className="stepper">
          <button
            type="button"
            className="stepper__btn"
            aria-label={`Decrease reps for set ${index + 1}`}
            onClick={() => onChange(Math.max(0, reps - 1))}
          >
            −
          </button>
          <span className="stepper__value">{reps}</span>
          <button
            type="button"
            className="stepper__btn"
            aria-label={`Increase reps for set ${index + 1}`}
            onClick={() => onChange(reps + 1)}
          >
            +
          </button>
        </div>

        <button
          type="button"
          className={confirmed ? 'set-row__confirm set-row__confirm--active' : 'set-row__confirm'}
          aria-label={`Confirm ${reps} reps for set ${index + 1}`}
          aria-pressed={confirmed}
          onClick={onConfirm}
        >
          ✓
        </button>
      </div>
    </div>
  )
}
