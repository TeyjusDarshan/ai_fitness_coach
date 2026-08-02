interface Props {
  secondsLeft: number
  totalSeconds: number
}

const SIZE = 220
const STROKE = 14
const RADIUS = (SIZE - STROKE) / 2
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

export function CircularCountdown({ secondsLeft, totalSeconds }: Props) {
  const progress = totalSeconds > 0 ? Math.max(0, Math.min(1, secondsLeft / totalSeconds)) : 0
  const dashOffset = CIRCUMFERENCE * (1 - progress)

  return (
    <svg width={SIZE} height={SIZE} className="countdown-ring">
      <circle
        cx={SIZE / 2}
        cy={SIZE / 2}
        r={RADIUS}
        fill="none"
        stroke="var(--hairline)"
        strokeWidth={STROKE}
      />
      <circle
        cx={SIZE / 2}
        cy={SIZE / 2}
        r={RADIUS}
        fill="none"
        stroke="var(--accent)"
        strokeWidth={STROKE}
        strokeLinecap="round"
        strokeDasharray={CIRCUMFERENCE}
        strokeDashoffset={dashOffset}
        transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
        style={{ transition: 'stroke-dashoffset 1s linear' }}
      />
      <text x="50%" y="50%" textAnchor="middle" dy="0.35em" className="countdown-ring__number">
        {secondsLeft}
      </text>
    </svg>
  )
}
