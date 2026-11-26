import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Icon } from '../components/Icon'
import { MaintainGauge, ProgressBar, StatusChip, WeekChange, WeightTrendChart } from '../components/Weight'
import { fetchWeight } from '../api'
import { TA } from '../foodText'
import { useAppState } from '../state/AppStateContext'
import type { WeightOverview } from '../types'
import { todayIsoIn } from '../utils'
import { kg } from '../weight'

type Range = 4 | 8 | 12 | 'all'
const RANGES: Range[] = [4, 8, 12, 'all']

// Weight Trend (/food/weight): range tabs, today's reading with this week's
// average and vs last week, a chart of weekly averages with calorie-change
// markers, then her status — a gauge for maintain, start → target for
// lose / gain — labelled with last Sunday's decision.
export function WeightScreen() {
  const { userId, timezone } = useAppState()
  const navigate = useNavigate()
  const [weight, setWeight] = useState<WeightOverview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [range, setRange] = useState<Range>(8)

  useEffect(() => {
    if (!userId) return
    fetchWeight(userId, todayIsoIn(timezone))
      .then((data) => {
        setWeight(data)
        setError(null)
      })
      .catch(() => setError(TA.failed))
  }, [userId, timezone])

  const shown = weight ? (range === 'all' ? weight.weeks : weight.weeks.slice(-range)) : []

  return (
    <div className="screen food-screen weight-screen" lang="ta">
      <button className="back-link" onClick={() => navigate('/food')}>
        <Icon name="chevronLeft" size={18} />
        {TA.back}
      </button>
      <h1 className="screen-title food-screen__title">{TA.weightTrend}</h1>

      <div className="weight-range" role="tablist" aria-label={TA.whichWeeks}>
        {RANGES.map((option) => (
          <button
            key={option}
            role="tab"
            aria-selected={range === option}
            className={`weight-range__option${range === option ? ' weight-range__option--on' : ''}`}
            onClick={() => setRange(option)}
          >
            {option === 'all' ? TA.allWeeks : TA.weeks(option)}
          </button>
        ))}
      </div>

      {error && <div className="error-banner">{error}</div>}
      {!weight && !error && <div className="spinner" />}

      {weight && (
        <>
          <section className="card weight-top">
            <div className="weight-top__main">
              <span className="weight-top__icon" aria-hidden>
                <Icon name="scale" size={26} />
              </span>
              <div>
                {weight.today ? (
                  <p className="weight-top__today">
                    {weight.today.weight_kg.toFixed(1)}
                    <span> kg</span>
                  </p>
                ) : (
                  <p className="weight-card__prompt">
                    <Icon name="whatsapp" size={18} />
                    {TA.sendWeightToday}
                  </p>
                )}
                <p className="weight-top__label">{TA.todaysWeight}</p>
                {weight.this_week.avg_kg !== null && (
                  <p className="weight-card__avg">
                    {TA.thisWeekAverage}: <strong>{kg(weight.this_week.avg_kg)}</strong>
                  </p>
                )}
              </div>
            </div>
            <WeekChange weight={weight} large />
          </section>

          <section className="card weight-trend">
            <h2 className="weight-section-title">
              <Icon name="chart" size={22} />
              {TA.weeklyAverages}
            </h2>
            {shown.length > 0 ? (
              <WeightTrendChart weeks={shown} changes={weight.calorie_changes} />
            ) : (
              <p className="weight-trend__empty">
                {weight.readings_needed > 0 ? TA.recordMoreDays(weight.readings_needed) : TA.firstWeekPending}
              </p>
            )}
          </section>

          <section className="card weight-status-card">
            <h2 className="weight-section-title">
              <Icon name="target" size={22} />
              {weight.goal === 'maintain' ? TA.yourStatus : TA.yourProgress}
            </h2>
            {weight.goal === 'maintain' ? <MaintainGauge weight={weight} /> : <ProgressBar weight={weight} />}
            <div className="weight-status-card__chip">
              <StatusChip status={weight.status} />
            </div>
          </section>
        </>
      )}
    </div>
  )
}
