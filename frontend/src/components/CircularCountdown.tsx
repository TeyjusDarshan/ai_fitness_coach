import type { ReactNode } from 'react'

interface Props {
  secondsLeft: number
  totalSeconds: number
  // Replaces the plain number in the middle (e.g. "00:28 Remaining").
  children?: ReactNode
  size?: number
  stroke?: number
}

export function CircularCountdown({ secondsLeft, totalSeconds, children, size = 220, stroke = 14 }: Props) {
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const progress = totalSeconds > 0 ? Math.max(0, Math.min(1, secondsLeft / totalSeconds)) : 0
  const dashOffset = circumference * (1 - progress)

  return (
    <div className="countdown-ring" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--hairline)" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--accent)"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: 'stroke-dashoffset 1s linear' }}
        />
        {children === undefined && (
          <text x="50%" y="50%" textAnchor="middle" dy="0.35em" className="countdown-ring__number">
            {secondsLeft}
          </text>
        )}
      </svg>
      {children !== undefined && <div className="countdown-ring__center">{children}</div>}
    </div>
  )
}
