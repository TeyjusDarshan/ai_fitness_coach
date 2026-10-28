// Asked of women before a fresh workout starts; a yes lowers that session's
// reps. See useStartWorkout.
export function PeriodPrompt({
  open,
  onAnswer,
  onCancel,
}: {
  open: boolean
  onAnswer: (isPeriod: boolean) => void
  onCancel: () => void
}) {
  if (!open) return null
  return (
    <div className="period-prompt" role="dialog" aria-modal="true" aria-labelledby="period-prompt-title" onClick={onCancel}>
      <div className="period-prompt__card" onClick={(e) => e.stopPropagation()}>
        <h2 id="period-prompt-title" className="period-prompt__title">
          Are you on your period?
        </h2>
        <p className="period-prompt__text">
          If yes, today&apos;s workout is made lighter for you.
        </p>
        <button className="btn-primary" onClick={() => onAnswer(true)}>
          Yes
        </button>
        <button className="btn-secondary" onClick={() => onAnswer(false)}>
          No
        </button>
      </div>
    </div>
  )
}
