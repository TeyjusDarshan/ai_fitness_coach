import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Icon, type IconName } from '../components/Icon'
import { createMealLog, deleteMealLog, fetchDietDay, fetchRecentDiet } from '../api'
import { dishName, MEAL_LABELS, MEAL_ORDER, portionLabel } from '../food'
import { formatTamilDay, TA } from '../foodText'
import { useAppState } from '../state/AppStateContext'
import { useVoiceRecorder } from '../state/useVoiceRecorder'
import type { DietDay, DietDaySummary, DietGoals, MealItem, RecentDiet } from '../types'
import { formatClock, todayIsoIn } from '../utils'

const PAST_DAYS = 10

type Tab = 'today' | 'past'

// The four goal nutrients next to the calorie ring, each with its colour.
const GOAL_BARS: { key: keyof DietGoals; label: string; tone: string }[] = [
  { key: 'protein_g', label: TA.protein, tone: 'protein' },
  { key: 'fibre_g', label: TA.fibre, tone: 'fibre' },
  { key: 'carbs_g', label: TA.carbs, tone: 'carbs' },
  { key: 'fat_g', label: TA.fat, tone: 'fat' },
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
    <section className="card food-goal" aria-label={TA.dailyGoal}>
      <h2 className="food-goal__title">
        <Icon name="target" size={24} />
        {TA.dailyGoal}
      </h2>
      <div className="food-goal__body">
        <div
          className="food-goal__ring"
          role="progressbar"
          aria-label={TA.calories}
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
  // Meals she said she didn't eat; shown only while that meal has no dishes.
  const skipped = new Set(counted.flatMap((log) => log.skipped_meals ?? []))
  const groups = MEAL_ORDER.map((meal) => ({
    meal,
    items: items.filter((item) => item.meal === meal),
    skipped: meal !== null && skipped.has(meal),
  })).filter((group) => group.items.length > 0 || group.skipped)

  return (
    <>
      {waiting.map((log) => (
        <button key={log.id} className="food-notice" onClick={() => onOpenLog(log.id)}>
          <span className="spinner spinner--small" aria-hidden />
          {TA.workingOutOne}
          <Icon name="chevronRight" size={18} />
        </button>
      ))}
      {failed.map((log) => (
        <div key={log.id} className="food-notice food-notice--failed">
          {TA.couldNotUnderstandOne}
          <button className="btn-link" onClick={() => onRemoveLog(log.id)}>
            {TA.remove}
          </button>
        </div>
      ))}
      {groups.length === 0 && waiting.length === 0 && <p className="food-screen__empty">{emptyText}</p>}
      {groups.map((group) => (
        <section key={group.meal ?? 'other'} className="food-meal">
          <h2 className="food-meal__title">{MEAL_LABELS[group.meal ?? 'other']}</h2>
          <div className="card food-meal__items">
            {group.items.length === 0 && (
              <div className="food-item-row food-item-row--skipped">
                <span className="food-item-row__name">{TA.skippedMeal}</span>
              </div>
            )}
            {group.items.map((item) => (
              <button key={item.id} className="food-item-row" onClick={() => onOpenItem(item)}>
                <span className="food-item-row__text">
                  <span className="food-item-row__name">{dishName(item)}</span>
                  <span className="food-item-row__portion">
                    {item.assumed ? TA.about : ''}
                    {portionLabel(item)}
                  </span>
                </span>
                <span className="food-item-row__protein">
                  {item.needs_review ? TA.beingChecked : TA.proteinG(item.protein_g)}
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
  { key: 'energy_kcal', label: TA.calories, unit: 'kcal', icon: 'flame' },
  { key: 'protein_g', label: TA.protein, unit: 'g', icon: 'dumbbell' },
  { key: 'carbs_g', label: TA.carbs, unit: 'g', icon: 'wheat' },
  { key: 'fibre_g', label: TA.fibre, unit: 'g', icon: 'leaf' },
  { key: 'fat_g', label: TA.fat, unit: 'g', icon: 'drop' },
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
  const { timezone } = useAppState()
  // Her own today (her time zone), the darker bar on the right.
  const today = todayIsoIn(timezone)
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
        <span className="food-chart__avg">{average === null ? TA.noLogsYet : TA.average(amount(average, unit))}</span>
        <span className="food-chart__target">
          <span className="food-chart__dot" aria-hidden />
          {TA.recommended(amount(target, unit))}
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
              aria-label={`${formatTamilDay(day.date)}: ${day.dishes ? amount(value, unit) : TA.nothingLogged}`}
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
        <h2 className="food-overview__title">{TA.overview}</h2>
        <p className="food-overview__sub">{TA.overviewSub(days.length)}</p>
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
  const { userId, timezone } = useAppState()
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

  // "Today" is her own day (user_profiles.timezone), matching the date the
  // server logs a recording or WhatsApp check-in for.
  const shownDate = tab === 'today' ? todayIsoIn(timezone) : pastDate

  const loadDay = useCallback(() => {
    if (!userId || !shownDate) return
    fetchDietDay(userId, shownDate)
      .then((data) => {
        setDay(data)
        setError(null)
      })
      .catch(() => setError(TA.failed))
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
      .catch(() => setError(TA.failed))
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
    if (date === todayIsoIn(timezone)) chooseTab('today')
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
        tab === 'today' ? TA.emptyToday : TA.emptyDay
      }
    />
  )

  return (
    <div className="screen food-screen food-screen--with-mic" lang="ta">
      <button className="back-link" onClick={() => (pastDate ? setPastDate(null) : navigate('/'))}>
        <Icon name="chevronLeft" size={18} />
        {pastDate ? TA.allDays : TA.back}
      </button>
      <h1 className="screen-title food-screen__title">{TA.title}</h1>

      <div className="food-day-toggle" role="tablist" aria-label={TA.whichDays}>
        <button
          role="tab"
          aria-selected={tab === 'today'}
          className={`food-day-toggle__option${tab === 'today' ? ' food-day-toggle__option--on' : ''}`}
          disabled={recording || sending}
          onClick={() => chooseTab('today')}
        >
          {TA.today}
        </button>
        <button
          role="tab"
          aria-selected={tab === 'past'}
          className={`food-day-toggle__option${tab === 'past' ? ' food-day-toggle__option--on' : ''}`}
          disabled={recording || sending}
          onClick={() => chooseTab('past')}
        >
          {TA.pastDays(PAST_DAYS)}
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {tab === 'past' &&
        !pastDate &&
        (recent ? <NutritionOverview recent={recent} onOpen={openDay} /> : <div className="spinner" />)}

      {shownDate && (
        <>
          {pastDate && <p className="food-screen__date">{formatTamilDay(pastDate)}</p>}
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
                {recorder.error ? (
                  TA.micBlocked
                ) : (
                  <>
                    {TA.sendFailed}{' '}
                    <button className="btn-link" onClick={() => unsent.current && void send(unsent.current)}>
                      {TA.tryAgain}
                    </button>
                  </>
                )}
              </div>
            )}
            <button
              className={`food-mic__button${recording ? ' food-mic__button--live' : ''}`}
              onClick={() => (recording ? recorder.stop() : void recorder.start())}
              disabled={sending}
              aria-label={recording ? TA.stopRecording : TA.record}
            >
              {sending ? (
                <span className="spinner spinner--small food-mic__spinner" aria-hidden />
              ) : (
                <Icon name={recording ? 'stop' : 'mic'} size={recording ? 28 : 34} />
              )}
            </button>
            <span className="food-mic__bubble">
              {sending ? TA.sending : recording ? TA.listening(formatClock(recorder.seconds)) : TA.tapToRecord}
            </span>
          </div>
        ) : (
          <div className="error-banner">{TA.noMic}</div>
        ))}
    </div>
  )
}
