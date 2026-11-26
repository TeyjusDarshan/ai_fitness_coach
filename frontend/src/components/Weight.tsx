// The weight pieces of the Diet screens: the card at the top of Food's
// Today tab, and the chart, progress bar and gauge of the Weight Trend
// screen. Weight is only shown here; she sends it on WhatsApp.
import { useId } from 'react'
import { Icon } from './Icon'
import { TA } from '../foodText'
import type { CalorieChange, WeightOverview, WeightStatus, WeightWeek } from '../types'
import {
  currentAverage,
  kg,
  maintainBand,
  progressFraction,
  shortTamilDate,
  signedKg,
  weekChange,
} from '../weight'

// This week's average vs last week's: green toward her goal, grey away.
export function WeekChange({ weight, large = false }: { weight: WeightOverview; large?: boolean }) {
  const result = weekChange(weight)
  if (!result) return null
  const icon = result.change > 0 ? 'trendUp' : result.change < 0 ? 'trendDown' : 'trendFlat'
  return (
    <div className={`weight-change${result.toward ? ' weight-change--toward' : ''}${large ? ' weight-change--large' : ''}`}>
      <span className="weight-change__value">
        <Icon name={icon} size={large ? 26 : 20} />
        {signedKg(result.change)}
      </span>
      <span className="weight-change__label">{TA.vsLastWeek}</span>
    </div>
  )
}

const GOOD: WeightStatus[] = ['on_track', 'in_range', 'target_reached']

export function StatusChip({ status }: { status: WeightStatus | null }) {
  if (!status) return null
  const good = GOOD.includes(status)
  return (
    <span className={`weight-status${good ? ' weight-status--good' : ''}`}>
      {good && <Icon name="check" size={16} />}
      {TA.weightStatus[status]}
    </span>
  )
}

// Start → target, filled to this week's average.
export function ProgressBar({ weight, compact = false }: { weight: WeightOverview; compact?: boolean }) {
  const average = currentAverage(weight)
  if (weight.target_kg === null) return null
  const fraction = average === null ? 0 : progressFraction(weight, average)
  return (
    <div className={`weight-progress${compact ? ' weight-progress--compact' : ''}`}>
      {!compact && average !== null && (
        <div className="weight-progress__pin-row">
          <span className="weight-progress__pin" style={{ left: `${fraction * 100}%` }}>
            {kg(average)}
          </span>
        </div>
      )}
      <div
        className="weight-progress__track"
        role="progressbar"
        aria-label={TA.yourProgress}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(fraction * 100)}
      >
        <div className="weight-progress__fill" style={{ width: `${fraction * 100}%` }} />
        {!compact && <span className="weight-progress__marker" style={{ left: `${fraction * 100}%` }} />}
      </div>
      <div className="weight-progress__ends">
        <span>
          <small>{TA.startWeight}</small>
          {kg(weight.start_kg)}
        </span>
        <span className="weight-progress__end--target">
          <small>{TA.targetWeight}</small>
          {kg(weight.target_kg)}
        </span>
      </div>
    </div>
  )
}

// Half circle over the maintain band (±2.5% of the weight she's keeping):
// green in the middle to red at both limits, the needle at this week's
// average. The only place weight is ever shown in red.
export function MaintainGauge({ weight, compact = false }: { weight: WeightOverview; compact?: boolean }) {
  const gradientId = useId()
  const { keep, low, high } = maintainBand(weight)
  const average = currentAverage(weight)
  const fraction = average === null ? 0.5 : Math.min(1, Math.max(0, (average - low) / (high - low)))
  const r = 80
  const cx = 100
  const cy = 95
  const angle = Math.PI * (1 - fraction)
  const nx = cx + r * Math.cos(angle)
  const ny = cy - r * Math.sin(angle)
  return (
    <div className={`weight-gauge${compact ? ' weight-gauge--compact' : ''}`}>
      <svg viewBox="0 0 200 110" role="img" aria-label={`${TA.yourStatus}: ${average === null ? '' : kg(average)}`}>
        <defs>
          <linearGradient id={gradientId} x1="0" x2="1" y1="0" y2="0">
            <stop offset="0" stopColor="#d1694f" />
            <stop offset="0.18" stopColor="#e8a33d" />
            <stop offset="0.36" stopColor="#2e8b57" />
            <stop offset="0.64" stopColor="#2e8b57" />
            <stop offset="0.82" stopColor="#e8a33d" />
            <stop offset="1" stopColor="#d1694f" />
          </linearGradient>
        </defs>
        <path
          d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`}
          fill="none"
          stroke={`url(#${gradientId})`}
          strokeWidth={compact ? 16 : 14}
          strokeLinecap="round"
        />
        <line className="weight-gauge__needle" x1={cx} y1={cy} x2={nx} y2={ny} />
        <circle className="weight-gauge__hub" cx={cx} cy={cy} r={compact ? 7 : 5} />
        <circle className="weight-gauge__dot" cx={nx} cy={ny} r={compact ? 9 : 8} />
      </svg>
      {!compact && (
        <>
          <div className="weight-gauge__center">
            {average !== null && <strong>{kg(average)}</strong>}
            <span>{TA.thisWeekAverage}</span>
          </div>
          <div className="weight-gauge__limits">
            <span>
              <strong>{kg(low)}</strong>
              {TA.lowerLimit}
            </span>
            <span>
              <strong>{kg(high)}</strong>
              {TA.upperLimit}
            </span>
          </div>
          <p className="weight-gauge__keep">{TA.keepingWeight(kg(keep))}</p>
        </>
      )}
    </div>
  )
}

// The card at the top of Food's Today tab: today's reading (or a prompt to
// send it on WhatsApp), this week's average, vs last week, and her progress
// bar (lose / gain) or a mini gauge (maintain).
export function WeightCard({ weight, onOpen }: { weight: WeightOverview; onOpen: () => void }) {
  const average = weight.this_week.avg_kg
  return (
    <section className="card weight-card" aria-label={TA.weight}>
      <div className="weight-card__head">
        <h2 className="weight-card__title">
          <Icon name="scale" size={26} />
          {TA.weight}
        </h2>
        <button className="weight-card__more" onClick={onOpen}>
          {TA.seeDetails}
          <Icon name="chevronRight" size={16} />
        </button>
      </div>
      <div className="weight-card__body">
        <div className="weight-card__main">
          {weight.today ? (
            <p className="weight-card__today" aria-label={TA.todaysWeight}>
              {weight.today.weight_kg.toFixed(1)}
              <span> kg</span>
            </p>
          ) : (
            <p className="weight-card__prompt">
              <Icon name="whatsapp" size={20} />
              {TA.sendWeightToday}
            </p>
          )}
          {average !== null && (
            <p className="weight-card__avg">
              {TA.thisWeekAverage}: <strong>{kg(average)}</strong>
            </p>
          )}
          <WeekChange weight={weight} />
        </div>
        <div className="weight-card__side">
          {weight.goal === 'maintain' ? <MaintainGauge weight={weight} compact /> : <ProgressBar weight={weight} compact />}
        </div>
      </div>
    </section>
  )
}

function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

// Chart geometry (SVG user units).
const W = 320
const H = 190
const PAD = { left: 34, right: 18, top: 34, bottom: 26 }

function niceRange(values: number[]): { min: number; max: number; step: number } {
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const span = Math.max(2, hi - lo)
  const step = span > 6 ? 2 : 1
  const min = Math.floor((lo - 0.4) / step) * step
  const max = Math.ceil((hi + 0.4) / step) * step
  return { min, max: Math.max(max, min + 2 * step), step }
}

// Weekly averages as a line over an area fill, the latest labelled, with a
// dashed marker where her calories changed. No daily readings, no target.
export function WeightTrendChart({ weeks, changes }: { weeks: WeightWeek[]; changes: CalorieChange[] }) {
  const fillId = useId()
  const { min, max, step } = niceRange(weeks.map((w) => w.avg_kg))
  const innerW = W - PAD.left - PAD.right
  const innerH = H - PAD.top - PAD.bottom
  const x = (i: number) => PAD.left + (weeks.length === 1 ? innerW / 2 : (i / (weeks.length - 1)) * innerW)
  const y = (v: number) => PAD.top + ((max - v) / (max - min)) * innerH
  const points = weeks.map((w, i) => [x(i), y(w.avg_kg)] as const)
  const line = points.map(([px, py], i) => `${i ? 'L' : 'M'} ${px} ${py}`).join(' ')
  const area = `${line} L ${points.at(-1)![0]} ${PAD.top + innerH} L ${points[0][0]} ${PAD.top + innerH} Z`
  const ticks: number[] = []
  for (let v = min; v <= max + 1e-9; v += step) ticks.push(v)

  // A change sits on the week it falls in; changes outside the shown weeks
  // are left out.
  const markers = changes
    .map((change) => ({ change, index: weeks.findLastIndex((w) => w.week_start <= change.date) }))
    .filter(({ change, index }) => index >= 0 && change.date < addDays(weeks[index].week_start, 7))

  const labelIdx = weeks.length > 2 ? [0, Math.floor((weeks.length - 1) / 2), weeks.length - 1] : weeks.map((_, i) => i)
  const last = points.at(-1)!
  const latest = weeks.at(-1)!
  const bubbleW = 66
  const bubbleX = Math.min(W - bubbleW - 2, Math.max(PAD.left, last[0] - bubbleW / 2))

  return (
    <svg className="weight-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${TA.weeklyAverages}: ${weeks.map((w) => `${shortTamilDate(w.week_start)} ${kg(w.avg_kg)}`).join(', ')}`}>
      <defs>
        <linearGradient id={fillId} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#2e8b57" stopOpacity="0.28" />
          <stop offset="1" stopColor="#2e8b57" stopOpacity="0.02" />
        </linearGradient>
      </defs>
      {ticks.map((t) => (
        <g key={t}>
          <line className="weight-chart__grid" x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} />
          <text className="weight-chart__tick" x={PAD.left - 8} y={y(t) + 4} textAnchor="end">
            {t}
          </text>
        </g>
      ))}
      {markers.map(({ change, index }) => (
        <g key={change.date} className="weight-chart__marker">
          <line x1={x(index)} x2={x(index)} y1={PAD.top - 6} y2={PAD.top + innerH} />
          <text x={x(index)} y={PAD.top - 12} textAnchor={index === weeks.length - 1 ? 'end' : index === 0 ? 'start' : 'middle'}>
            {TA.calorieChange(String(change.to_kcal))}
          </text>
        </g>
      ))}
      {weeks.length > 1 && <path d={area} fill={`url(#${fillId})`} />}
      {weeks.length > 1 && <path className="weight-chart__line" d={line} />}
      {points.slice(0, -1).map(([px, py], i) => (
        <circle key={weeks[i].week_start} className="weight-chart__point" cx={px} cy={py} r={weeks.length > 16 ? 2.5 : 3.5} />
      ))}
      <circle className="weight-chart__halo" cx={last[0]} cy={last[1]} r={9} />
      <circle className="weight-chart__latest" cx={last[0]} cy={last[1]} r={5} />
      <g className="weight-chart__bubble">
        <rect x={bubbleX} y={Math.max(2, last[1] - 34)} width={bubbleW} height={22} rx={11} />
        <text x={bubbleX + bubbleW / 2} y={Math.max(2, last[1] - 34) + 15} textAnchor="middle">
          {kg(latest.avg_kg)}
        </text>
      </g>
      {labelIdx.map((i) => (
        <text
          key={i}
          className="weight-chart__tick"
          x={x(i)}
          y={H - 6}
          textAnchor={weeks.length === 1 ? 'middle' : i === 0 ? 'start' : i === weeks.length - 1 ? 'end' : 'middle'}
        >
          {shortTamilDate(weeks[i].week_start)}
        </text>
      ))}
    </svg>
  )
}
