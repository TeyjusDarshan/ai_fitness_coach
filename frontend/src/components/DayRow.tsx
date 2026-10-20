import type { DashboardDay } from '../types'
import { formatDayDate } from '../utils'

interface Props {
  day: DashboardDay
  timerLabel: string | null
  onStart: () => void
}

export function DayRow({ day, timerLabel, onStart }: Props) {
  const { status, split_name: splitName, locked } = day
  const dateLabel = formatDayDate(day.date)

  return (
    <div className={`day-row day-row--${status}${locked ? ' day-row--locked' : ''}`}>
      <div className="day-row__label">
        <div className="day-row__heading">
          <span className="day-row__weekday">{dateLabel}</span>
          {status !== 'rest' && <span className="day-row__split">: {splitName}</span>}
        </div>
        {status !== 'rest' && timerLabel && (
          <span className="day-row__timer">Timer: {timerLabel}</span>
        )}
      </div>

      {status === 'completed' && <span className="day-row__check" aria-label="Completed">✓</span>}
      {status === 'missed' && <span className="day-row__missed">Missed</span>}
      {status === 'next' && !locked && (
        <button className="day-row__start" onClick={onStart}>
          Start <span aria-hidden>›</span>
        </button>
      )}
      {status === 'next' && locked && <span className="day-row__opens">Opens {dateLabel}</span>}
    </div>
  )
}
