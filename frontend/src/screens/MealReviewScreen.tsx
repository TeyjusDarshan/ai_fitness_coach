import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Icon } from '../components/Icon'
import { confirmMealLog, deleteMealItem, deleteMealLog, fetchMealLog, setMealItemQuantity } from '../api'
import { dishName, MEAL_LOG_ERRORS, nextQuantity, portionLabel } from '../food'
import { TA } from '../foodText'
import type { MealItem, MealLog } from '../types'

const POLL_MS = 2000
// Taps on − / + are sent once she pauses, not one request per tap.
const SAVE_DELAY_MS = 500

// What was heard in one recording: a "working it out" wait, then a card per
// dish with − / + for the portion and a remove button. Tapping a dish opens
// its ingredients.
export function MealReviewScreen() {
  const navigate = useNavigate()
  const logId = Number(useParams().logId)
  const [log, setLog] = useState<MealLog | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const saveTimers = useRef(new Map<number, number>())

  useEffect(() => {
    let stopped = false
    let timer: number | undefined
    const poll = () => {
      fetchMealLog(logId)
        .then((data) => {
          if (stopped) return
          setLog(data)
          if (data.status === 'processing') timer = window.setTimeout(poll, POLL_MS)
        })
        .catch(() => {
          if (!stopped) setError(TA.failed)
        })
    }
    poll()
    const timers = saveTimers.current
    return () => {
      stopped = true
      window.clearTimeout(timer)
      timers.forEach((id) => window.clearTimeout(id))
    }
  }, [logId])

  function patchItem(id: number, change: Partial<MealItem>) {
    setLog((prev) => prev && { ...prev, items: prev.items.map((item) => (item.id === id ? { ...item, ...change } : item)) })
  }

  function step(item: MealItem, direction: 1 | -1) {
    const quantity = nextQuantity(item, direction)
    if (quantity === null) return
    // Shown straight away; grams and protein follow in proportion.
    const ratio = quantity / item.quantity
    patchItem(item.id, {
      quantity,
      assumed: false,
      grams: item.grams === null ? null : Math.round(item.grams * ratio * 10) / 10,
      protein_g: Math.round(item.protein_g * ratio * 10) / 10,
    })
    window.clearTimeout(saveTimers.current.get(item.id))
    saveTimers.current.set(
      item.id,
      window.setTimeout(() => {
        saveTimers.current.delete(item.id)
        setMealItemQuantity(item.id, quantity)
          .then((saved) => {
            // A newer tap is already waiting to be sent: keep what she sees.
            if (!saveTimers.current.has(item.id)) patchItem(item.id, saved)
          })
          .catch(() => setError(TA.failed))
      }, SAVE_DELAY_MS),
    )
  }

  function remove(item: MealItem) {
    window.clearTimeout(saveTimers.current.get(item.id))
    saveTimers.current.delete(item.id)
    setLog((prev) => prev && { ...prev, items: prev.items.filter((other) => other.id !== item.id) })
    deleteMealItem(item.id).catch(() => setError(TA.failed))
  }

  async function done() {
    setBusy(true)
    try {
      await confirmMealLog(logId)
      navigate('/food', { replace: true })
    } catch {
      setError(TA.failed)
      setBusy(false)
    }
  }

  async function recordAgain() {
    setBusy(true)
    await deleteMealLog(logId).catch(() => undefined)
    navigate('/food', { replace: true })
  }

  if (!log) {
    return (
      <div className="screen food-screen" lang="ta">
        {error ? <div className="error-banner">{error}</div> : <div className="spinner" />}
        {error && (
          <button className="btn-secondary" onClick={() => navigate('/food', { replace: true })}>
            {TA.backToFood}
          </button>
        )}
      </div>
    )
  }

  if (log.status === 'processing') {
    return (
      <div className="screen food-screen food-wait" lang="ta">
        <div className="spinner" />
        <h1 className="food-wait__title">{TA.workingOut}</h1>
        <p className="food-wait__hint">{TA.workingOutHint}</p>
        <button className="btn-secondary" onClick={() => navigate('/food', { replace: true })}>
          {TA.backToFood}
        </button>
      </div>
    )
  }

  if (log.status === 'failed') {
    return (
      <div className="screen food-screen food-wait" lang="ta">
        <h1 className="food-wait__title">{TA.tryThatAgain}</h1>
        <p className="food-wait__hint">{MEAL_LOG_ERRORS[log.error ?? 'failed']}</p>
        <button className="btn-primary" disabled={busy} onClick={() => void recordAgain()}>
          <Icon name="mic" size={20} /> {TA.recordAgain}
        </button>
      </div>
    )
  }

  return (
    <div className="screen food-screen" lang="ta">
      <h1 className="screen-title food-screen__title">{TA.heard}</h1>
      <p className="food-screen__lead">{TA.heardLead}</p>
      {error && <div className="error-banner">{error}</div>}

      {log.items.length === 0 && <p className="food-screen__empty">{TA.nothingLeft}</p>}
      <div className="food-review">
        {log.items.map((item) => (
          <div key={item.id} className="card food-card">
            <button className="food-card__main" onClick={() => navigate(`/food/item/${item.id}`)}>
              <span className="food-card__name">{dishName(item)}</span>
              <span className="food-card__meta">
                {item.needs_review ? TA.newDish : TA.proteinG(item.protein_g)}
              </span>
              {item.assumed && <span className="food-card__guess">{TA.guessed}</span>}
            </button>
            <button className="food-card__remove" onClick={() => remove(item)} aria-label={TA.removeThing(dishName(item))}>
              <Icon name="close" size={18} />
            </button>
            <div className="food-stepper">
              <button
                className="food-stepper__button"
                onClick={() => step(item, -1)}
                disabled={nextQuantity(item, -1) === null}
                aria-label={TA.less(dishName(item))}
              >
                <Icon name="minus" size={22} />
              </button>
              <span className="food-stepper__value" aria-live="polite">
                {portionLabel(item)}
              </span>
              <button
                className="food-stepper__button"
                onClick={() => step(item, 1)}
                disabled={nextQuantity(item, 1) === null}
                aria-label={TA.more(dishName(item))}
              >
                <Icon name="plus" size={22} />
              </button>
            </div>
          </div>
        ))}
      </div>

      <div className="food-screen__actions">
        <button className="btn-primary" disabled={busy} onClick={() => void done()}>
          <Icon name="check" size={20} /> {TA.done}
        </button>
        <button className="btn-secondary" disabled={busy} onClick={() => void recordAgain()}>
          {TA.recordAgain}
        </button>
      </div>
    </div>
  )
}
