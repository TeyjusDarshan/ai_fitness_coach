import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Icon } from '../components/Icon'
import { createMealLog, deleteMealLog, fetchDietDay } from '../api'
import { MEAL_LABELS, MEAL_ORDER, portionLabel } from '../food'
import { useAppState } from '../state/AppStateContext'
import { useVoiceRecorder } from '../state/useVoiceRecorder'
import type { DietDay, MealItem } from '../types'
import { appTodayIso, formatClock, formatDayDate } from '../utils'

type DayChoice = 'today' | 'yesterday'

function isoFor(choice: DayChoice): string {
  if (choice === 'today') return appTodayIso()
  const date = new Date(`${appTodayIso()}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() - 1)
  return date.toISOString().slice(0, 10)
}

function ProgressBar({ label, value, target }: { label: string; value: number; target: number }) {
  const percent = Math.min(100, Math.round((value / target) * 100))
  return (
    <div className="food-progress">
      <div className="food-progress__head">
        <span className="food-progress__label">{label}</span>
        <span className="food-progress__value">
          <strong>{Math.round(value)}</strong> of {target} g
        </span>
      </div>
      <div
        className="food-progress__track"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={target}
        aria-valuenow={Math.round(value)}
      >
        <div className="food-progress__fill" style={{ width: `${percent}%` }} />
      </div>
    </div>
  )
}

// The Food home: say what you ate (one recording, sent as soon as she stops),
// see protein and fibre for the day, and open anything logged to fix it.
export function FoodScreen() {
  const { userId } = useAppState()
  const navigate = useNavigate()
  const [choice, setChoice] = useState<DayChoice>('today')
  const [day, setDay] = useState<DietDay | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  // Kept so a failed upload can be retried without recording again.
  const unsent = useRef<Blob | null>(null)
  const [sendFailed, setSendFailed] = useState(false)

  const load = useCallback(() => {
    if (!userId) return
    fetchDietDay(userId, isoFor(choice))
      .then((data) => {
        setDay(data)
        setError(null)
      })
      .catch((e: Error) => setError(e.message))
  }, [userId, choice])

  useEffect(() => {
    setDay(null)
    load()
  }, [load])

  const send = useCallback(
    async (recording: Blob) => {
      unsent.current = recording
      setSending(true)
      setSendFailed(false)
      try {
        const log = await createMealLog(recording, choice)
        navigate(`/food/log/${log.id}`)
      } catch {
        setSendFailed(true)
        setSending(false)
      }
    },
    [choice, navigate],
  )

  const recorder = useVoiceRecorder((recording) => void send(recording))
  const recording = recorder.phase === 'recording'

  async function removeLog(id: number) {
    await deleteMealLog(id).catch(() => undefined)
    load()
  }

  const counted = day?.logs.filter((log) => log.status === 'ready' || log.status === 'confirmed') ?? []
  const waiting = day?.logs.filter((log) => log.status === 'processing') ?? []
  const failed = day?.logs.filter((log) => log.status === 'failed') ?? []
  const items = counted.flatMap((log) => log.items)
  const groups = MEAL_ORDER.map((meal) => ({
    meal,
    items: items.filter((item) => item.meal === meal),
  })).filter((group) => group.items.length > 0)

  const itemRow = (item: MealItem) => (
    <button key={item.id} className="food-item-row" onClick={() => navigate(`/food/item/${item.id}`)}>
      <span className="food-item-row__text">
        <span className="food-item-row__name">{item.name}</span>
        <span className="food-item-row__portion">
          {item.assumed ? 'about ' : ''}
          {portionLabel(item)}
          {item.own_recipe ? ' · your recipe' : ''}
        </span>
      </span>
      <span className="food-item-row__protein">
        {item.needs_review ? 'Being checked' : `${item.protein_g} g protein`}
      </span>
      <Icon name="chevronRight" size={18} className="food-item-row__chevron" />
    </button>
  )

  return (
    <div className="screen food-screen">
      <button className="back-link" onClick={() => navigate('/')}>
        <Icon name="chevronLeft" size={18} />
        Back
      </button>
      <h1 className="screen-title food-screen__title">Your Food</h1>

      <div className="food-day-toggle" role="tablist" aria-label="Which day">
        {(['today', 'yesterday'] as DayChoice[]).map((option) => (
          <button
            key={option}
            role="tab"
            aria-selected={choice === option}
            className={`food-day-toggle__option${choice === option ? ' food-day-toggle__option--on' : ''}`}
            disabled={recording || sending}
            onClick={() => setChoice(option)}
          >
            {option === 'today' ? 'Today' : 'Yesterday'}
          </button>
        ))}
      </div>
      <p className="food-screen__date">{formatDayDate(isoFor(choice))}</p>

      {error && <div className="error-banner">{error}</div>}

      {day && (
        <div className="card food-totals">
          <ProgressBar label="Protein" value={day.totals.protein_g} target={day.targets.protein_g} />
          <ProgressBar label="Fibre" value={day.totals.fibre_g} target={day.targets.fibre_g} />
        </div>
      )}

      {recorder.supported ? (
        <div className="card food-record">
          <button
            className={`food-record__mic${recording ? ' food-record__mic--live' : ''}`}
            onClick={() => (recording ? recorder.stop() : void recorder.start())}
            disabled={sending}
            aria-label={recording ? 'Stop recording' : 'Record what you ate'}
          >
            <Icon name={recording ? 'stop' : 'mic'} size={recording ? 32 : 40} />
          </button>
          {sending ? (
            <p className="food-record__title">Sending your recording…</p>
          ) : recording ? (
            <>
              <p className="food-record__title">Listening… {formatClock(recorder.seconds)}</p>
              <p className="food-record__hint">Tap the button when you have finished</p>
            </>
          ) : (
            <>
              <p className="food-record__title">
                Tell us what you ate {choice === 'today' ? 'today' : 'yesterday'}
              </p>
              <p className="food-record__hint">
                Say it the way you would tell a friend: “moonu idli, oru karandi sambar, oru tumbler coffee”
              </p>
            </>
          )}
          {recorder.error && <p className="food-record__error">{recorder.error}</p>}
          {sendFailed && !sending && (
            <p className="food-record__error" role="alert">
              We couldn&apos;t send your recording.{' '}
              <button className="btn-link" onClick={() => unsent.current && void send(unsent.current)}>
                Try again
              </button>
            </p>
          )}
        </div>
      ) : (
        <div className="error-banner">This browser can&apos;t record sound. Open the app in Chrome or Safari.</div>
      )}

      {waiting.map((log) => (
        <button key={log.id} className="food-notice" onClick={() => navigate(`/food/log/${log.id}`)}>
          <span className="spinner spinner--small" aria-hidden />
          Working out a recording…
          <Icon name="chevronRight" size={18} />
        </button>
      ))}
      {failed.map((log) => (
        <div key={log.id} className="food-notice food-notice--failed">
          We couldn&apos;t understand one recording.
          <button className="btn-link" onClick={() => void removeLog(log.id)}>
            Remove
          </button>
        </div>
      ))}

      {day && groups.length === 0 && waiting.length === 0 && (
        <p className="food-screen__empty">Nothing logged for {choice === 'today' ? 'today' : 'yesterday'} yet.</p>
      )}
      {groups.map((group) => (
        <section key={group.meal ?? 'other'} className="food-meal">
          <h2 className="food-meal__title">{MEAL_LABELS[group.meal ?? 'other']}</h2>
          <div className="card food-meal__items">{group.items.map(itemRow)}</div>
        </section>
      ))}
    </div>
  )
}
