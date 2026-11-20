import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Icon, type IconName } from '../components/Icon'
import { createMealLog, deleteMealLog, fetchDietDay, fetchRecentDiet } from '../api'
import { MEAL_LABELS, MEAL_ORDER, portionLabel } from '../food'
import { useAppState } from '../state/AppStateContext'
import { useVoiceRecorder } from '../state/useVoiceRecorder'
import type { DietDay, DietDaySummary, DietGoals, MealItem, RecentDiet } from '../types'
import { appTodayIso, formatClock, formatDayDate } from '../utils'

const PAST_DAYS = 10

type Tab = 'today' | 'past'

// The four goal nutrients next to the calorie ring, each with its colour.
const GOAL_BARS: { key: keyof DietGoals; label: string; tone: string }[] = [
  { key: 'protein_g', label: 'Protein', tone: 'protein' },
  { key: 'fibre_g', label: 'Fibre', tone: 'fibre' },
  { key: 'carbs_g', label: 'Carbs', tone: 'carbs' },
  { key: 'fat_g', label: 'Fats', tone: 'fat' },
]

const kcal = new Intl.NumberFormat('en-IN')

function percentOf(value: number, target: number): number {
  return target > 0 ? Math.round((value / target) * 100) : 0
}

// Calories as a ring and the four goal nutrients as bars, against her targets.
function GoalCard({ totals, targets }: { totals: DietGoals; targets: DietGoals }) {
  const radius = 52
  const circumference = 2 * Math.PI * radius
  const filled = Math.min(1, targets.energy_kcal > 0 ? totals.energy_kcal / targets.energy_kcal : 0) * circumference
  return (
    <section className="card food-goal" aria-label="Daily goal">
      <h2 className="food-goal__title">
        <Icon name="target" size={24} />
        Daily Goal
      </h2>
      <div className="food-goal__body">
        <div
          className="food-goal__ring"
          role="progressbar"
          aria-label="Calories"
          aria-valuemin={0}
          aria-valuemax={targets.energy_kcal}
          aria-valuenow={Math.round(totals.energy_kcal)}
        >
          <svg viewBox="0 0 120 120" aria-hidden>
            <circle className="food-goal__ring-track" cx="60" cy="60" r={radius} />
            {filled > 0 && (
              <circle
                className="food-goal__ring-fill"
                cx="60"
                cy="60"
                r={radius}
                strokeDasharray={`${filled} ${circumference}`}
              />
            )}
          </svg>
          <span className="food-goal__ring-text">
            <strong>{kcal.format(Math.round(totals.energy_kcal))}</strong>
            <span>/ {kcal.format(targets.energy_kcal)} kcal</span>
          </span>
        </div>
        <div className="food-goal__bars">
          {GOAL_BARS.map(({ key, label, tone }) => {
            const value = totals[key]
            const target = targets[key]
            return (
              <div key={key} className={`food-goal__bar food-goal__bar--${tone}`}>
                <div className="food-goal__bar-head">
                  <span className="food-goal__bar-label">{label}</span>
                  <span className="food-goal__bar-value">
                    {Math.round(value)} / {target} g
                  </span>
                </div>
                <div
                  className="food-goal__track"
                  role="progressbar"
                  aria-label={label}
                  aria-valuemin={0}
                  aria-valuemax={target}
                  aria-valuenow={Math.round(value)}
                >
                  <div className="food-goal__fill" style={{ width: `${Math.min(100, percentOf(value, target))}%` }} />
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}

// A day's dishes grouped by meal, plus recordings still being worked out or
// that failed.
function DayMeals({
  day,
  onOpenItem,
  onOpenLog,
  onRemoveLog,
  emptyText,
}: {
  day: DietDay
  onOpenItem: (item: MealItem) => void
  onOpenLog: (id: number) => void
  onRemoveLog: (id: number) => void
  emptyText: string
}) {
  const counted = day.logs.filter((log) => log.status === 'ready' || log.status === 'confirmed')
  const waiting = day.logs.filter((log) => log.status === 'processing')
  const failed = day.logs.filter((log) => log.status === 'failed')
  const items = counted.flatMap((log) => log.items)
  const groups = MEAL_ORDER.map((meal) => ({
    meal,
    items: items.filter((item) => item.meal === meal),
  })).filter((group) => group.items.length > 0)

  return (
    <>
      {waiting.map((log) => (
        <button key={log.id} className="food-notice" onClick={() => onOpenLog(log.id)}>
          <span className="spinner spinner--small" aria-hidden />
          Working out a recording…
          <Icon name="chevronRight" size={18} />
        </button>
      ))}
      {failed.map((log) => (
        <div key={log.id} className="food-notice food-notice--failed">
          We couldn&apos;t understand one recording.
          <button className="btn-link" onClick={() => onRemoveLog(log.id)}>
            Remove
          </button>
        </div>
      ))}
      {groups.length === 0 && waiting.length === 0 && <p className="food-screen__empty">{emptyText}</p>}
      {groups.map((group) => (
        <section key={group.meal ?? 'other'} className="food-meal">
          <h2 className="food-meal__title">{MEAL_LABELS[group.meal ?? 'other']}</h2>
          <div className="card food-meal__items">
            {group.items.map((item) => (
              <button key={item.id} className="food-item-row" onClick={() => onOpenItem(item)}>
                <span className="food-item-row__text">
                  <span className="food-item-row__name">{item.name}</span>
                  <span className="food-item-row__portion">
                    {item.assumed ? 'about ' : ''}
                    {portionLabel(item)}
                  </span>
                </span>
                <span className="food-item-row__protein">
                  {item.needs_review ? 'Being checked' : `${item.protein_g} g protein`}
                </span>
                <Icon name="chevronRight" size={18} className="food-item-row__chevron" />
              </button>
            ))}
          </div>
        </section>
      ))}
    </>
  )
}

// One chart of the Nutrition Overview for each goal nutrient.
const OVERVIEW: {
  key: keyof DietGoals
  label: string
  unit: string
  icon: IconName
}[] = [
  { key: 'energy_kcal', label: 'Calories', unit: 'kcal', icon: 'flame' },
  { key: 'protein_g', label: 'Protein', unit: 'g', icon: 'dumbbell' },
  { key: 'carbs_g', label: 'Carbs', unit: 'g', icon: 'wheat' },
  { key: 'fibre_g', label: 'Fibre', unit: 'g', icon: 'leaf' },
  { key: 'fat_g', label: 'Fat', unit: 'g', icon: 'drop' },
]

function amount(value: number, unit: string): string {
  return `${kcal.format(Math.round(value))} ${unit}`
}

// One nutrient across the days, oldest on the left: a bar per day (today's
// darker), a dashed line at her target, and the average over the days she
// logged anything. Tapping a bar opens that day.
function NutrientChart({
  days,
  target,
  label,
  unit,
  icon,
  valueOf,
  onOpen,
}: {
  days: DietDaySummary[]
  target: number
  label: string
  unit: string
  icon: IconName
  valueOf: (day: DietDaySummary) => number
  onOpen: (date: string) => void
}) {
  const today = appTodayIso()
  const logged = days.filter((day) => day.dishes > 0)
  const average = logged.length ? logged.reduce((sum, day) => sum + valueOf(day), 0) / logged.length : null
  const scale = Math.max(target, ...days.map(valueOf)) * 1.1 || 1
  return (
    <section className="card food-chart">
      <div className="food-chart__head">
        <span className="food-chart__title">
          <Icon name={icon} size={22} />
          {label}
        </span>
        <span className="food-chart__avg">{average === null ? 'No logs yet' : `Avg. ${amount(average, unit)}`}</span>
        <span className="food-chart__target">
          <span className="food-chart__dot" aria-hidden />
          Recommended: {amount(target, unit)}
        </span>
      </div>
      <div className="food-chart__plot">
        <div className="food-chart__line" style={{ bottom: `${(target / scale) * 100}%` }} aria-hidden />
        {days.map((day) => {
          const value = valueOf(day)
          return (
            <button
              key={day.date}
              className="food-chart__col"
              onClick={() => onOpen(day.date)}
              aria-label={`${formatDayDate(day.date)}: ${day.dishes ? amount(value, unit) : 'nothing logged'}`}
            >
              <span
                className={`food-chart__bar${day.date === today ? ' food-chart__bar--today' : ''}${day.dishes ? '' : ' food-chart__bar--empty'}`}
                style={{
                  height: day.dishes ? `${Math.max(4, (value / scale) * 100)}%` : undefined,
                }}
              />
            </button>
          )
        })}
      </div>
      <div className="food-chart__labels" aria-hidden>
        {days.map((day) => (
          <span key={day.date} className={day.date === today ? 'food-chart__label--today' : undefined}>
            {Number(day.date.slice(8, 10))}
          </span>
        ))}
      </div>
    </section>
  )
}

// The last 10 days as a chart per goal nutrient, today on the right.
function NutritionOverview({ recent, onOpen }: { recent: RecentDiet; onOpen: (date: string) => void }) {
  const days = [...recent.days].reverse()
  return (
    <>
      <div className="food-overview__head">
        <h2 className="food-overview__title">Nutrition Overview</h2>
        <p className="food-overview__sub">
          Your intake over the last {days.length} days. Tap a day to see what you ate.
        </p>
      </div>
      {OVERVIEW.map(({ key, label, unit, icon }) => (
        <NutrientChart
          key={key}
          days={days}
          target={recent.targets[key]}
          label={label}
          unit={unit}
          icon={icon}
          valueOf={(day) => day.totals[key]}
          onOpen={onOpen}
        />
      ))}
    </>
  )
}

// The Food home. Today: her calories and goal nutrients for the day, what
// she logged by meal, and the mic (a recording is sent as soon as she
// stops, always for today). Past 10 Day Logs: a chart per goal nutrient over
// her last 10 days; tapping a day opens its goal card and dishes.
export function FoodScreen() {
  const { userId } = useAppState()
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('today')
  const [day, setDay] = useState<DietDay | null>(null)
  const [recent, setRecent] = useState<RecentDiet | null>(null)
  // The past day opened from the list, if any.
  const [pastDate, setPastDate] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  // Kept so a failed upload can be retried without recording again.
  const unsent = useRef<Blob | null>(null)
  const [sendFailed, setSendFailed] = useState(false)

  const shownDate = tab === 'today' ? appTodayIso() : pastDate

  const loadDay = useCallback(() => {
    if (!userId || !shownDate) return
    fetchDietDay(userId, shownDate)
      .then((data) => {
        setDay(data)
        setError(null)
      })
      .catch((e: Error) => setError(e.message))
  }, [userId, shownDate])

  useEffect(() => {
    setDay(null)
    loadDay()
  }, [loadDay])

  useEffect(() => {
    if (tab !== 'past' || !userId) return
    fetchRecentDiet(userId, PAST_DAYS)
      .then((data) => {
        setRecent(data)
        setError(null)
      })
      .catch((e: Error) => setError(e.message))
  }, [tab, userId])

  const send = useCallback(
    async (recording: Blob) => {
      unsent.current = recording
      setSending(true)
      setSendFailed(false)
      try {
        const log = await createMealLog(recording, 'today')
        navigate(`/food/log/${log.id}`)
      } catch {
        setSendFailed(true)
        setSending(false)
      }
    },
    [navigate],
  )

  const recorder = useVoiceRecorder((recording) => void send(recording))
  const recording = recorder.phase === 'recording'

  async function removeLog(id: number) {
    await deleteMealLog(id).catch(() => undefined)
    loadDay()
  }

  // A day tapped in the overview; today opens on the Today tab.
  function openDay(date: string) {
    if (date === appTodayIso()) chooseTab('today')
    else setPastDate(date)
  }

  function chooseTab(next: Tab) {
    setTab(next)
    setPastDate(null)
  }

  const meals = day && (
    <DayMeals
      day={day}
      onOpenItem={(item) => navigate(`/food/item/${item.id}`)}
      onOpenLog={(id) => navigate(`/food/log/${id}`)}
      onRemoveLog={(id) => void removeLog(id)}
      emptyText={
        tab === 'today'
          ? 'Nothing logged today yet. Tap the mic and say what you ate, the way you would tell a friend: “moonu idli, oru karandi sambar, oru tumbler coffee”.'
          : 'Nothing was logged on this day.'
      }
    />
  )

  return (
    <div className="screen food-screen food-screen--with-mic">
      <button className="back-link" onClick={() => (pastDate ? setPastDate(null) : navigate('/'))}>
        <Icon name="chevronLeft" size={18} />
        {pastDate ? 'All days' : 'Back'}
      </button>
      <h1 className="screen-title food-screen__title">Your Food</h1>

      <div className="food-day-toggle" role="tablist" aria-label="Which days">
        <button
          role="tab"
          aria-selected={tab === 'today'}
          className={`food-day-toggle__option${tab === 'today' ? ' food-day-toggle__option--on' : ''}`}
          disabled={recording || sending}
          onClick={() => chooseTab('today')}
        >
          Today
        </button>
        <button
          role="tab"
          aria-selected={tab === 'past'}
          className={`food-day-toggle__option${tab === 'past' ? ' food-day-toggle__option--on' : ''}`}
          disabled={recording || sending}
          onClick={() => chooseTab('past')}
        >
          Past {PAST_DAYS} Day Logs
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {tab === 'past' &&
        !pastDate &&
        (recent ? <NutritionOverview recent={recent} onOpen={openDay} /> : <div className="spinner" />)}

      {shownDate && (
        <>
          {pastDate && <p className="food-screen__date">{formatDayDate(pastDate)}</p>}
          {day ? (
            <>
              <GoalCard totals={day.totals} targets={day.targets} />
              {meals}
            </>
          ) : (
            !error && <div className="spinner" />
          )}
        </>
      )}

      {!pastDate &&
        (recorder.supported ? (
          <div className="food-mic" aria-live="polite">
            {(recorder.error || (sendFailed && !sending)) && (
              <div className="food-mic__bubble food-mic__bubble--error" role="alert">
                {recorder.error ?? (
                  <>
                    We couldn&apos;t send your recording.{' '}
                    <button className="btn-link" onClick={() => unsent.current && void send(unsent.current)}>
                      Try again
                    </button>
                  </>
                )}
              </div>
            )}
            <button
              className={`food-mic__button${recording ? ' food-mic__button--live' : ''}`}
              onClick={() => (recording ? recorder.stop() : void recorder.start())}
              disabled={sending}
              aria-label={recording ? 'Stop recording' : 'Record what you ate'}
            >
              {sending ? (
                <span className="spinner spinner--small food-mic__spinner" aria-hidden />
              ) : (
                <Icon name={recording ? 'stop' : 'mic'} size={recording ? 28 : 34} />
              )}
            </button>
            <span className="food-mic__bubble">
              {sending
                ? 'Sending…'
                : recording
                  ? `Listening ${formatClock(recorder.seconds)} · tap to stop`
                  : 'Tap to record'}
            </span>
          </div>
        ) : (
          <div className="error-banner">This browser can&apos;t record sound. Open the app in Chrome or Safari.</div>
        ))}
    </div>
  )
}
