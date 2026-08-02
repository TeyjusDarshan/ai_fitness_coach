import type { DashboardDay } from '../types'

interface Props {
  day: DashboardDay
  weekday: string
  timerLabel: string | null
  onStart: () => void
}

export function DayRow({ day, weekday, timerLabel, onStart }: Props) {
  const { status, split_name: splitName } = day

  return (
    <div className={`day-row day-row--${status}`}>
      <div className="day-row__label">
        <div className="day-row__heading">
          <span className="day-row__weekday">{weekday}</span>
          {status !== 'rest' && <span className="day-row__split">: {splitName}</span>}
        </div>
        {status !== 'rest' && timerLabel && (
          <span className="day-row__timer">Timer: {timerLabel}</span>
        )}
      </div>

      {status === 'completed' && <span className="day-row__check" aria-label="Completed">✓</span>}
      {status === 'next' && (
        <button className="day-row__start" onClick={onStart}>
          Start <span aria-hidden>›</span>
        </button>
      )}
    </div>
  )
}
