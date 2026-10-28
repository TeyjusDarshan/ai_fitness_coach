// Asked of women before a fresh workout starts; a yes lowers that session's
// reps. See useStartWorkout.
export function PeriodPrompt({
  open,
  adjusting,
  onAnswer,
  onCancel,
}: {
  open: boolean
  // A "yes" is being applied: show the "personalizing" popup instead.
  adjusting: boolean
  onAnswer: (isPeriod: boolean) => void
  onCancel: () => void
}) {
  if (adjusting) return <AdjustingPopup />
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

// Shown while a period session's reps are being lowered (a second or so), so
// the change doesn't happen silently.
function AdjustingPopup() {
  return (
    <div className="period-prompt period-prompt--center" role="alertdialog" aria-live="polite" aria-labelledby="adjusting-title">
      <div className="adjusting">
        <div className="adjusting__art" aria-hidden="true">
          <svg className="adjusting__ring" viewBox="0 0 100 100">
            <circle cx="50" cy="50" r="44" className="adjusting__track" />
            <circle cx="50" cy="50" r="44" className="adjusting__arc" />
          </svg>
          <svg className="adjusting__flower" viewBox="0 0 48 48" width="44" height="44">
            <g fill="currentColor">
              <ellipse cx="24" cy="13" rx="8" ry="10" />
              <ellipse cx="24" cy="35" rx="8" ry="10" />
              <ellipse cx="13" cy="24" rx="10" ry="8" />
              <ellipse cx="35" cy="24" rx="10" ry="8" />
            </g>
            <circle cx="24" cy="24" r="5" fill="#fff" opacity=".35" />
          </svg>
          <svg className="adjusting__heart adjusting__heart--a" viewBox="0 0 24 24" width="16" height="16">
            <path fill="currentColor" d="M12 21s-7.5-4.6-9.6-9.2C.9 8.4 3 5 6.3 5c2 0 3.5 1.1 4.2 2.5h3C14.2 6.1 15.7 5 17.7 5 21 5 23.1 8.4 21.6 11.8 19.5 16.4 12 21 12 21Z" />
          </svg>
          <svg className="adjusting__heart adjusting__heart--b" viewBox="0 0 24 24" width="12" height="12">
            <path fill="currentColor" d="M12 21s-7.5-4.6-9.6-9.2C.9 8.4 3 5 6.3 5c2 0 3.5 1.1 4.2 2.5h3C14.2 6.1 15.7 5 17.7 5 21 5 23.1 8.4 21.6 11.8 19.5 16.4 12 21 12 21Z" />
          </svg>
        </div>
        <h2 id="adjusting-title" className="adjusting__title">
          Personalizing today&apos;s workout
        </h2>
        <p className="adjusting__text">
          Making your exercises easier based on your cycle. This will only take a moment.
        </p>
        <p className="adjusting__wait">
          <span className="adjusting__spinner" />
          Please wait…
        </p>
      </div>
    </div>
  )
}
