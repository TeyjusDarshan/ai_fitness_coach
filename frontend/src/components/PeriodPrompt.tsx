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
        <div className="period-prompt__head">
          <div className="period-prompt__badge" aria-hidden="true">
            <svg className="period-prompt__drop" viewBox="0 0 24 24" width="30" height="30">
              <path
                fill="currentColor"
                d="M12 2.5c-.4 0-.8.2-1 .5C8.6 6.2 5.5 9.9 5.5 14a6.5 6.5 0 0 0 13 0c0-4.1-3.1-7.8-5.5-11-.2-.3-.6-.5-1-.5Z"
              />
              <path fill="#fff" fillOpacity=".4" d="M9 14.2c0 1.8 1 3 2.6 3.4a.7.7 0 0 0 .3-1.4c-.9-.2-1.5-.9-1.5-2a.7.7 0 0 0-1.4 0Z" />
            </svg>
            <svg className="period-prompt__heart period-prompt__heart--a" viewBox="0 0 24 24" width="14" height="14">
              <path fill="currentColor" d="M12 21s-7.5-4.6-9.6-9.2C.9 8.4 3 5 6.3 5c2 0 3.5 1.1 4.2 2.5h3C14.2 6.1 15.7 5 17.7 5 21 5 23.1 8.4 21.6 11.8 19.5 16.4 12 21 12 21Z" />
            </svg>
            <svg className="period-prompt__heart period-prompt__heart--b" viewBox="0 0 24 24" width="11" height="11">
              <path fill="currentColor" d="M12 21s-7.5-4.6-9.6-9.2C.9 8.4 3 5 6.3 5c2 0 3.5 1.1 4.2 2.5h3C14.2 6.1 15.7 5 17.7 5 21 5 23.1 8.4 21.6 11.8 19.5 16.4 12 21 12 21Z" />
            </svg>
          </div>
          <div>
            <h2 id="period-prompt-title" className="period-prompt__title">
              Are you on your period?
            </h2>
            <p className="period-prompt__text">If yes, today&apos;s workout is made lighter for you.</p>
          </div>
        </div>
        <div className="period-prompt__yes">
          <button className="period-prompt__btn period-prompt__btn--yes" onClick={() => onAnswer(true)}>
            Yes
          </button>
        </div>
        <button className="period-prompt__btn period-prompt__btn--no" onClick={() => onAnswer(false)}>
          No
        </button>
      </div>
    </div>
  )
}
