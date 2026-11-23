import { Fragment, useEffect, useState } from 'react'
import { ApiError } from '../../api'
import {
  fetchClientDiet,
  fetchMealAudioUrl,
  saveNutritionTargets,
  setDietTracking,
  type ClientDiet,
  type CoachMealItem,
  type CoachMealLog,
  type DietSetup,
  type NutritionTargets,
} from '../../adminApi'
import { portionLabel } from '../../food'
import { formatDayDate } from '../../utils'
import { NUTRIENT_LABELS, nutrientValue } from './foodLabels'

// The day's columns; every other nutrient is listed when the day is opened.
const SUMMARY_KEYS = ['energy_kcal', 'protein_g', 'carbs_g', 'fibre_g', 'fat_g', 'saturated_fat_g', 'unsaturated_fat_g']
const DETAIL_KEYS = Object.keys(NUTRIENT_LABELS).filter((key) => !SUMMARY_KEYS.includes(key))

const DAYS = 7

// Coach-only: what a client said she ate over the last week — every nutrient
// per day, and under each day the recordings, what was heard in them, the
// ingredients assumed, and what she changed. Her daily protein and fibre
// targets are set here. Diet tracking is off for a client until the coach
// switches it on here; while it's off she has no Food in her app.
export function ClientFood({
  adminKey,
  userId,
  initiallyEnabled,
  onUnauthorized,
}: {
  adminKey: string
  userId: string
  initiallyEnabled: boolean
  onUnauthorized: () => void
}) {
  const [enabled, setEnabled] = useState(initiallyEnabled)
  const [switching, setSwitching] = useState(false)
  const [diet, setDiet] = useState<ClientDiet | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)

  async function switchTracking(on: boolean) {
    setSwitching(true)
    setError(null)
    try {
      setEnabled((await setDietTracking(adminKey, userId, on)).diet_enabled)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return onUnauthorized()
      setError(err instanceof Error ? err.message : 'Could not change diet tracking.')
    } finally {
      setSwitching(false)
    }
  }

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    setDiet(null)
    setError(null)
    fetchClientDiet(adminKey, userId, DAYS)
      .then((data) => !cancelled && setDiet(data))
      .catch((err) => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 401) onUnauthorized()
        else setError(err instanceof Error ? err.message : 'Could not load the food log.')
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adminKey, userId, enabled])

  if (!enabled) {
    return (
      <div className="card admin__section client-food">
        <h3 className="monitor__section-title">Diet tracking</h3>
        <p className="admin__muted">
          Off for this client. She doesn&apos;t see Food in her app and can&apos;t log what she eats.
        </p>
        {error && <div className="error-banner">{error}</div>}
        <div className="monitor__row">
          <button className="btn-secondary client-food__switch" disabled={switching} onClick={() => void switchTracking(true)}>
            {switching ? 'Turning on…' : 'Turn on diet tracking'}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="card admin__section client-food">
      <div className="client-food__head">
        <h3 className="monitor__section-title">Food, last {DAYS} days</h3>
        <button type="button" className="btn-link" disabled={switching} onClick={() => void switchTracking(false)}>
          {switching ? 'Turning off…' : 'Turn off diet tracking'}
        </button>
      </div>
      {error && <div className="error-banner">{error}</div>}
      {!diet && !error && <p className="admin__muted">Loading…</p>}
      {diet && (
        <>
          <SetupLine setup={diet.setup} />
          <Targets
            adminKey={adminKey}
            userId={userId}
            initial={diet.targets}
            onSaved={(targets) => setDiet({ ...diet, targets })}
            onUnauthorized={onUnauthorized}
          />
          {diet.days.length === 0 ? (
            <p className="admin__muted">Nothing logged in this period.</p>
          ) : (
            <div className="costs__scroll">
              <table className="costs__table">
                <thead>
                  <tr>
                    <th>Day</th>
                    <th className="costs__num">Energy</th>
                    <th className="costs__num">Protein</th>
                    <th className="costs__num">Carbs</th>
                    <th className="costs__num">Fibre</th>
                    <th className="costs__num">Fat</th>
                    <th className="costs__num">Saturated</th>
                    <th className="costs__num">Unsaturated</th>
                  </tr>
                </thead>
                <tbody>
                  {diet.days.map((day) => {
                    const expanded = open === day.date
                    return (
                      <Fragment key={day.date}>
                        <tr
                          className={`costs__row${expanded ? ' costs__row--open' : ''}`}
                          onClick={() => setOpen(expanded ? null : day.date)}
                        >
                          <td>
                            <button type="button" className="costs__client" aria-expanded={expanded}>
                              <span className="costs__caret" aria-hidden>
                                {expanded ? '▾' : '▸'}
                              </span>
                              <span className="costs__name">{formatDayDate(day.date)}</span>
                            </button>
                          </td>
                          {SUMMARY_KEYS.map((key) => (
                            <td key={key} className={`costs__num${key === 'protein_g' ? ' costs__total' : ''}`}>
                              {nutrientValue(key, day.totals[key])}
                            </td>
                          ))}
                        </tr>
                        {expanded && (
                          <tr className="costs__detail">
                            <td colSpan={8}>
                              <dl className="client-food__micros">
                                {DETAIL_KEYS.map((key) => (
                                  <div key={key}>
                                    <dt>{NUTRIENT_LABELS[key][0]}</dt>
                                    <dd>{nutrientValue(key, day.totals[key])}</dd>
                                  </div>
                                ))}
                              </dl>
                              {day.logs.map((log) => (
                                <LogBlock key={log.id} log={log} adminKey={adminKey} onUnauthorized={onUnauthorized} />
                              ))}
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
          <p className="admin__muted client-food__note">
            Estimates: Claude works out each dish&apos;s ingredients and their raw grams for her portion, and the
            nutrients come from the ingredient reference table.
          </p>
        </>
      )}
    </div>
  )
}

// Her daily goals, as the coach sets them (blank = back to the default).
const TARGET_FIELDS: { key: keyof NutritionTargets; label: string }[] = [
  { key: 'energy_kcal', label: 'Calories (kcal / day)' },
  { key: 'protein_g', label: 'Protein (g / day)' },
  { key: 'fibre_g', label: 'Fibre (g / day)' },
  { key: 'carbs_g', label: 'Carbs (g / day)' },
  { key: 'fat_g', label: 'Fat (g / day)' },
]

const GOAL_TEXT = { lose: 'lose weight', maintain: 'maintain weight', gain: 'gain weight' }

// Her one-time setup: what she entered, her BMI and the goal she chose.
function SetupLine({ setup }: { setup: DietSetup | null }) {
  if (!setup) {
    return <p className="admin__muted">Not set up yet — she'll be asked when she opens Diet.</p>
  }
  const target = setup.target_weight_kg
    ? ` · target ${setup.target_weight_kg} kg` +
      (setup.target_date
        ? ` by ${new Date(setup.target_date).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' })} (~${setup.weekly_change_kg} kg/week)`
        : ' (no date: little room under the calorie floor)')
    : ''
  const chose = setup.goal_confirmed
    ? `agreed to ${GOAL_TEXT[setup.goal]}`
    : `chose to ${GOAL_TEXT[setup.goal]} (we suggested ${GOAL_TEXT[setup.recommended_goal]})`
  return (
    <p className="client-food__setup">
      Setup {new Date(setup.completed_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}:{' '}
      {setup.height_cm} cm, {setup.weight_kg} kg, {setup.age} y · BMI {setup.bmi} ({setup.bmi_category}) ·
      maintenance {setup.tdee} kcal · {chose}, worked out {setup.calculated_targets.energy_kcal} kcal
      {target}
    </p>
  )
}

function asText(targets: NutritionTargets): Record<keyof NutritionTargets, string> {
  return Object.fromEntries(TARGET_FIELDS.map(({ key }) => [key, String(targets[key])])) as Record<
    keyof NutritionTargets,
    string
  >
}

function Targets({
  adminKey,
  userId,
  initial,
  onSaved,
  onUnauthorized,
}: {
  adminKey: string
  userId: string
  initial: NutritionTargets
  onSaved: (targets: NutritionTargets) => void
  onUnauthorized: () => void
}) {
  const [values, setValues] = useState(() => asText(initial))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const changed = TARGET_FIELDS.some(({ key }) => Number(values[key]) !== initial[key])

  async function save() {
    setBusy(true)
    setError(null)
    try {
      const result = await saveNutritionTargets(
        adminKey,
        userId,
        Object.fromEntries(
          TARGET_FIELDS.map(({ key }) => [key, values[key].trim() ? Number(values[key]) : null]),
        ) as Record<keyof NutritionTargets, number | null>,
      )
      onSaved(result.targets)
      setValues(asText(result.targets))
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return onUnauthorized()
      setError(err instanceof Error ? err.message : 'Failed to save the targets.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="client-food__targets">
        {TARGET_FIELDS.map(({ key, label }) => (
          <label key={key}>
            <span className="monitor__label">{label}</span>
            <input
              className="login-screen__input"
              inputMode="numeric"
              value={values[key]}
              onChange={(e) => setValues({ ...values, [key]: e.target.value })}
              disabled={busy}
            />
          </label>
        ))}
        <button className="btn-secondary" disabled={busy || !changed} onClick={() => void save()}>
          {busy ? 'Saving…' : 'Save targets'}
        </button>
      </div>
      {error && <div className="error-banner">{error}</div>}
    </>
  )
}

const LOG_STATUS: Record<CoachMealLog['status'], string> = {
  processing: 'Being worked out',
  ready: 'Not reviewed by her',
  confirmed: 'Reviewed by her',
  failed: 'Could not be understood',
}

function LogBlock({
  log,
  adminKey,
  onUnauthorized,
}: {
  log: CoachMealLog
  adminKey: string
  onUnauthorized: () => void
}) {
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [audioError, setAudioError] = useState<string | null>(null)

  async function play() {
    setAudioError(null)
    try {
      setAudioUrl((await fetchMealAudioUrl(adminKey, log.id)).url)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return onUnauthorized()
      setAudioError('Could not load the recording.')
    }
  }

  return (
    <div className="client-food__log">
      <div className="monitor__row">
        <span className={`monitor__chip${log.status === 'failed' ? ' monitor__chip--severe' : ''}`}>
          {LOG_STATUS[log.status]}
        </span>
        {log.source === 'whatsapp' && <span className="monitor__chip">WhatsApp</span>}
        {log.skipped_meals?.length > 0 && (
          <span className="monitor__chip">Skipped: {log.skipped_meals.join(', ')}</span>
        )}
        <span className="admin__muted">
          {log.source === 'whatsapp' ? 'Sent' : 'Recorded'}{' '}
          {new Date(log.created_at).toLocaleString('en-GB', {
            day: 'numeric',
            month: 'short',
            hour: '2-digit',
            minute: '2-digit',
          })}
        </span>
        {log.has_audio &&
          (audioUrl ? (
            <audio src={audioUrl} controls autoPlay />
          ) : (
            <button type="button" className="btn-link" onClick={() => void play()}>
              Play recording
            </button>
          ))}
      </div>
      {audioError && <div className="error-banner">{audioError}</div>}
      {log.transcript && <p className="client-food__transcript">“{log.transcript}”</p>}
      {log.items.map((item) => (
        <ItemBlock key={item.id} item={item} />
      ))}
    </div>
  )
}

function ItemBlock({ item }: { item: CoachMealItem }) {
  const n = item.nutrients
  return (
    <div className="client-food__item">
      <div className="monitor__row">
        <strong>{item.name}</strong>
        <span>
          {portionLabel(item)}
          {item.grams !== null && item.unit !== 'grams' ? ` (${Math.round(item.grams)} g)` : ''}
        </span>
        {item.meal && <span className="admin__muted">{item.meal}</span>}
        {item.assumed && <span className="monitor__chip monitor__chip--mild">Amount assumed</span>}
        {item.needs_review && <span className="monitor__chip monitor__chip--severe">Dish not worked out</span>}
        {item.edited && <span className="monitor__chip">Edited by her</span>}
      </div>
      {!item.needs_review && (
        <p className="admin__muted client-food__line">
          {nutrientValue('energy_kcal', n.energy_kcal)} · protein {nutrientValue('protein_g', n.protein_g)} · carbs{' '}
          {nutrientValue('carbs_g', n.carbs_g)} · fibre {nutrientValue('fibre_g', n.fibre_g)} · fat{' '}
          {nutrientValue('fat_g', n.fat_g)}
        </p>
      )}
      {item.ingredients.length > 0 && (
        <p className="client-food__line">
          {item.ingredients.map((ingredient, i) => (
            <span key={ingredient.ingredient_id} className={ingredient.edited ? 'client-food__changed' : undefined}>
              {i > 0 && ', '}
              {ingredient.name} {Math.round(ingredient.grams * 10) / 10} g
              {ingredient.edited && ingredient.grams !== ingredient.default_grams
                ? ` (was ${Math.round(ingredient.default_grams * 10) / 10} g)`
                : ''}
            </span>
          ))}
        </p>
      )}
    </div>
  )
}
