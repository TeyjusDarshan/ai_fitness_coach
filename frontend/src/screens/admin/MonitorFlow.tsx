import { useEffect, useMemo, useState } from 'react'
import { ApiError } from '../../api'
import {
  editPrescription,
  fetchClientMonitor,
  fetchClients,
  fetchFeedbackAudioUrl,
  regeneratePlan,
  saveCoachNotes,
  type ClientMonitor,
  type ClientSummary,
  type MonitorWorkout,
} from '../../adminApi'
import { LoggedSets, Prescription } from '../../components/ExerciseLog'
import { capitalize, formatDayDate, formatDuration, repUnit, targetRepsForSet, WORKOUT_STATUS_LABELS } from '../../utils'
import type { ExerciseEntry } from '../../types'
import { humanize } from './planDraft'

// Coach-only, read-only view of one client at a time: profile basics, joint
// pain, period days, app sign-in, then every scheduled and past workout with
// what was logged, the AI analysis and the client's own voice feedback.
// An upcoming workout's sets and reps can be edited per exercise, and the
// current week's coach notes edited or the week rebuilt from progression.
export function MonitorFlow({ adminKey, onUnauthorized }: { adminKey: string; onUnauthorized: () => void }) {
  const [clients, setClients] = useState<ClientSummary[] | null>(null)
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [monitor, setMonitor] = useState<ClientMonitor | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function handleError(err: unknown, fallback: string) {
    if (err instanceof ApiError && err.status === 401) {
      onUnauthorized()
      return
    }
    setError(err instanceof Error ? err.message : fallback)
  }

  useEffect(() => {
    fetchClients(adminKey)
      .then(setClients)
      .catch((err) => handleError(err, 'Failed to load clients.'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adminKey])

  async function openClient(userId: string) {
    setSelected(userId)
    setMonitor(null)
    setError(null)
    setLoading(true)
    try {
      setMonitor(await fetchClientMonitor(adminKey, userId))
    } catch (err) {
      handleError(err, 'Failed to load this client.')
    } finally {
      setLoading(false)
    }
  }

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (clients ?? []).filter(
      (c) => !q || c.user_id.toLowerCase().includes(q) || (c.name ?? '').toLowerCase().includes(q),
    )
  }, [clients, query])

  return (
    <div className="monitor">
      <aside className="card monitor__clients">
        <input
          className="login-screen__input"
          placeholder="Search by name or id"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {clients === null && !error && <p className="admin__muted">Loading clients…</p>}
        <ul className="monitor__client-list">
          {shown.map((c) => (
            <li key={c.user_id}>
              <button
                className={`monitor__client${selected === c.user_id ? ' monitor__client--active' : ''}`}
                onClick={() => void openClient(c.user_id)}
              >
                <span className="monitor__client-name">{c.name ? capitalize(c.name) : c.user_id}</span>
                <span className="admin__muted">
                  {c.user_id}
                  {c.gender ? ` · ${c.gender}` : ''}
                </span>
                {!c.has_passkey && <span className="admin__pill">not signed up</span>}
              </button>
            </li>
          ))}
          {clients !== null && shown.length === 0 && <li className="admin__muted">No clients match.</li>}
        </ul>
      </aside>

      <section className="monitor__detail">
        {error && <div className="error-banner">{error}</div>}
        {!selected && !error && <p className="admin__muted">Pick a client to see their workouts.</p>}
        {loading && <div className="spinner" />}
        {monitor && (
          <ClientDetail
            adminKey={adminKey}
            monitor={monitor}
            onUnauthorized={onUnauthorized}
            onPlanChanged={() => void openClient(monitor.client.user_id)}
          />
        )}
      </section>
    </div>
  )
}

function ClientDetail({
  adminKey,
  monitor,
  onUnauthorized,
  onPlanChanged,
}: {
  adminKey: string
  monitor: ClientMonitor
  onUnauthorized: () => void
  onPlanChanged: () => void
}) {
  const { client, workouts } = monitor
  const p = client.profile
  return (
    <>
      <div className="card admin__section">
        <h2 className="admin__section-title">
          {client.name ? capitalize(client.name) : client.user_id}
          <span className="admin__muted">{client.user_id}</span>
        </h2>
        <dl className="monitor__facts">
          <Fact label="Gender" value={client.gender} />
          <Fact label="Age" value={p.age} />
          <Fact label="Goal" value={p.primary_goal && humanize(p.primary_goal)} />
          <Fact label="Experience" value={p.experience_level && humanize(p.experience_level)} />
          <Fact label="Days / week" value={p.days_per_week} />
          <Fact
            label="App sign-in"
            value={
              client.sign_in.passkeys === 0
                ? 'Not signed up yet'
                : client.sign_in.last_used_at
                  ? `Last signed in ${formatTimestamp(client.sign_in.last_used_at)}`
                  : 'Passkey set up, not signed in since'
            }
          />
        </dl>
        <div className="monitor__row">
          <span className="monitor__label">Joint pain</span>
          {client.joint_pain.length === 0 ? (
            <span className="admin__muted">None reported</span>
          ) : (
            client.joint_pain.map((jp) => (
              <span key={jp.joint} className={`monitor__chip monitor__chip--${jp.pain_level}`}>
                {humanize(jp.joint)} · {jp.pain_level}
              </span>
            ))
          )}
        </div>
        {client.gender === 'female' && (
          <div className="monitor__row">
            <span className="monitor__label">Period days</span>
            {client.period_days.length === 0 ? (
              <span className="admin__muted">None logged</span>
            ) : (
              client.period_days.map((d) => (
                <span key={d} className="monitor__chip monitor__chip--period">
                  {formatDayDate(d)}
                </span>
              ))
            )}
          </div>
        )}
      </div>

      {monitor.current_plan && (
        <CoachNotes
          // Remount when the week changes (e.g. after "Create progression").
          key={monitor.current_plan.id}
          adminKey={adminKey}
          userId={client.user_id}
          initial={monitor.current_plan.coach_notes ?? ''}
          onUnauthorized={onUnauthorized}
        />
      )}
      <RegeneratePlan
        adminKey={adminKey}
        userId={client.user_id}
        onUnauthorized={onUnauthorized}
        onDone={onPlanChanged}
      />
      <WorkoutSection title="Scheduled" workouts={workouts.scheduled} empty="Nothing scheduled.">
        {(w) => <WorkoutCard key={w.session_id} workout={w} adminKey={adminKey} onUnauthorized={onUnauthorized} />}
      </WorkoutSection>
      <WorkoutSection title="Past" workouts={workouts.past} empty="No past workouts yet.">
        {(w) => <WorkoutCard key={w.session_id} workout={w} adminKey={adminKey} onUnauthorized={onUnauthorized} />}
      </WorkoutSection>
    </>
  )
}

// The notes shown at the bottom of the client's dashboard. Saved on the
// current week; progression copies them into each following week.
function CoachNotes({
  adminKey,
  userId,
  initial,
  onUnauthorized,
}: {
  adminKey: string
  userId: string
  initial: string
  onUnauthorized: () => void
}) {
  const [saved, setSaved] = useState(initial)
  const [draft, setDraft] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [justSaved, setJustSaved] = useState(false)

  async function save() {
    setBusy(true)
    setError(null)
    try {
      const result = await saveCoachNotes(adminKey, userId, draft)
      const stored = result.coach_notes ?? ''
      setSaved(stored)
      setDraft(stored)
      setJustSaved(true)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onUnauthorized()
        return
      }
      setError(err instanceof Error ? err.message : 'Failed to save the notes.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card admin__section monitor__coach-notes">
      <label className="monitor__label" htmlFor="coach-notes">
        Coach notes
      </label>
      <textarea
        id="coach-notes"
        className="login-screen__input admin__textarea"
        rows={3}
        maxLength={2000}
        placeholder="Shown to the client at the bottom of their workouts."
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value)
          setJustSaved(false)
        }}
        disabled={busy}
      />
      <div className="monitor__row">
        <button className="btn-secondary" disabled={busy || draft.trim() === saved.trim()} onClick={() => void save()}>
          {busy ? 'Saving…' : 'Save notes'}
        </button>
        {justSaved && <span className="admin__muted">Saved</span>}
      </div>
      {error && <div className="error-banner">{error}</div>}
    </div>
  )
}

// "Create progression": throws away the current week's workouts and builds
// them again from last week's results (e.g. after the progression rules or
// her logged effort changed). Only allowed before any of them is started.
function RegeneratePlan({
  adminKey,
  userId,
  onUnauthorized,
  onDone,
}: {
  adminKey: string
  userId: string
  onUnauthorized: () => void
  onDone: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function regenerate() {
    if (
      !window.confirm(
        "Delete this week's upcoming workouts and create them again from last week's progression?",
      )
    )
      return
    setBusy(true)
    setError(null)
    try {
      await regeneratePlan(adminKey, userId)
      onDone()
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onUnauthorized()
        return
      }
      setError(err instanceof Error ? err.message : 'Failed to create the progression.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card admin__section monitor__regenerate">
      <button className="btn-secondary" disabled={busy} onClick={() => void regenerate()}>
        {busy ? 'Creating…' : 'Create progression'}
      </button>
      <span className="admin__muted">
        Rebuilds this week's workouts from last week's results, on the same dates.
      </span>
      {error && <div className="error-banner">{error}</div>}
    </div>
  )
}

function Fact({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value === null || value === undefined || value === '' ? '—' : value}</dd>
    </div>
  )
}

function WorkoutSection({
  title,
  workouts,
  empty,
  children,
}: {
  title: string
  workouts: MonitorWorkout[]
  empty: string
  children: (w: MonitorWorkout) => React.ReactNode
}) {
  return (
    <div className="monitor__section">
      <h3 className="monitor__section-title">
        {title} <span className="admin__muted">({workouts.length})</span>
      </h3>
      {workouts.length === 0 ? <p className="admin__muted">{empty}</p> : workouts.map(children)}
    </div>
  )
}

function WorkoutCard({
  workout,
  adminKey,
  onUnauthorized,
}: {
  workout: MonitorWorkout
  adminKey: string
  onUnauthorized: () => void
}) {
  const [open, setOpen] = useState(false)
  const [feedbackUrl, setFeedbackUrl] = useState<string | null>(null)
  const [feedbackError, setFeedbackError] = useState<string | null>(null)
  const [loadingFeedback, setLoadingFeedback] = useState(false)
  // Local copy so a saved edit shows straight away.
  const [exercises, setExercises] = useState(workout.exercises)
  const [editing, setEditing] = useState<number | null>(null)
  const done = workout.status === 'completed'
  const editable = workout.status === 'scheduled'

  async function loadFeedback() {
    setLoadingFeedback(true)
    setFeedbackError(null)
    try {
      setFeedbackUrl((await fetchFeedbackAudioUrl(adminKey, workout.session_id)).url)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onUnauthorized()
      else setFeedbackError(err instanceof Error ? err.message : 'Could not load the recording.')
    } finally {
      setLoadingFeedback(false)
    }
  }

  return (
    <div className={`card monitor__workout monitor__workout--${workout.status}`}>
      <button className="monitor__workout-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="monitor__workout-date">{formatDayDate(workout.date)}</span>
        <span className="monitor__workout-name">
          {workout.name ?? `Day ${workout.day_number}`}
          {workout.is_period && <span className="monitor__chip monitor__chip--period">Period</span>}
          {workout.analysis && <span className="monitor__chip">AI summary</span>}
          {workout.has_feedback && <span className="monitor__chip">Voice note</span>}
        </span>
        <span className={`workout-panel__status workout-panel__status--${workout.status}`}>
          {WORKOUT_STATUS_LABELS[workout.status]}
        </span>
      </button>
      {open && (
        <div className="monitor__workout-body">
          {workout.duration_seconds != null && (
            <p className="admin__muted">Took {formatDuration(workout.duration_seconds)}</p>
          )}
          {exercises.map((exercise) => (
            <div key={exercise.id} className="monitor__exercise">
              <div className="monitor__exercise-head">
                <span className="monitor__exercise-name">{exercise.name}</span>
                {editable && editing !== exercise.id && exercise.set_logs.length === 0 && (
                  <button className="btn-link" onClick={() => setEditing(exercise.id)}>
                    Edit
                  </button>
                )}
              </div>
              {editing === exercise.id ? (
                <PrescriptionEditor
                  exercise={exercise}
                  adminKey={adminKey}
                  onUnauthorized={onUnauthorized}
                  onSaved={(sets, reps, note) => {
                    setExercises((prev) =>
                      prev.map((ex) => (ex.id === exercise.id ? { ...ex, sets, reps, note } : ex)),
                    )
                    setEditing(null)
                  }}
                  onCancel={() => setEditing(null)}
                />
              ) : (
                <Prescription exercise={exercise} />
              )}
              {done && <LoggedSets exercise={exercise} />}
            </div>
          ))}

          {workout.analysis && (
            <div className="monitor__feedback">
              <div className="monitor__label">AI summary</div>
              <p className="monitor__analysis">{workout.analysis}</p>
              {workout.analysis_audio_url && <audio controls preload="none" src={workout.analysis_audio_url} />}
            </div>
          )}

          {workout.has_feedback && (
            <div className="monitor__feedback">
              <div className="monitor__label">Client&apos;s voice feedback</div>
              {feedbackUrl ? (
                <audio controls autoPlay src={feedbackUrl} />
              ) : (
                <button className="btn-link" disabled={loadingFeedback} onClick={() => void loadFeedback()}>
                  {loadingFeedback ? 'Loading…' : '▶ Play recording'}
                </button>
              )}
              {feedbackError && <div className="admin__hint admin__hint--error">{feedbackError}</div>}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// Sets plus one target per set (reps, or seconds for a timed exercise).
const MAX_SETS = 10

function PrescriptionEditor({
  exercise,
  adminKey,
  onUnauthorized,
  onSaved,
  onCancel,
}: {
  exercise: ExerciseEntry
  adminKey: string
  onUnauthorized: () => void
  onSaved: (sets: number, reps: string, note: string | null) => void
  onCancel: () => void
}) {
  const [note, setNote] = useState(exercise.note ?? '')
  const [targets, setTargets] = useState<string[]>(() =>
    Array.from({ length: exercise.sets ?? 1 }, (_, i) => String(targetRepsForSet(exercise, i))),
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const unit = repUnit(exercise)
  const values = targets.map(Number)
  const valid = values.every((v) => Number.isInteger(v) && v >= 1 && v <= 600)

  function setCount(next: number) {
    const count = Math.max(1, Math.min(MAX_SETS, next))
    // New sets copy the last one's target.
    setTargets((prev) =>
      count <= prev.length ? prev.slice(0, count) : [...prev, ...Array(count - prev.length).fill(prev[prev.length - 1] ?? '10')],
    )
  }

  async function save() {
    setSaving(true)
    setError(null)
    try {
      const result = await editPrescription(adminKey, exercise.id, values.length, values, note)
      onSaved(result.sets, result.reps, result.note)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onUnauthorized()
      else setError(err instanceof Error ? err.message : 'Could not save.')
      setSaving(false)
    }
  }

  return (
    <div className="monitor__editor">
      <div className="monitor__editor-sets">
        <span className="monitor__label">Sets</span>
        <button type="button" className="monitor__step" onClick={() => setCount(targets.length - 1)} disabled={targets.length <= 1}>
          −
        </button>
        <strong>{targets.length}</strong>
        <button type="button" className="monitor__step" onClick={() => setCount(targets.length + 1)} disabled={targets.length >= MAX_SETS}>
          +
        </button>
      </div>
      <div className="monitor__editor-targets">
        {targets.map((value, i) => (
          <label key={i} className="monitor__target">
            <span>Set {i + 1}</span>
            <input
              type="number"
              inputMode="numeric"
              min={1}
              max={600}
              value={value}
              onChange={(e) => setTargets((prev) => prev.map((v, j) => (j === i ? e.target.value : v)))}
            />
            <span className="admin__muted">{unit}</span>
          </label>
        ))}
      </div>
      <label className="monitor__editor-note">
        <span className="monitor__label">Coach note</span>
        <textarea
          className="login-screen__input admin__textarea"
          rows={2}
          maxLength={500}
          placeholder="e.g. Keep your back straight"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </label>
      {error && <div className="admin__hint admin__hint--error">{error}</div>}
      <div className="monitor__editor-actions">
        <button type="button" className="btn-link" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
        <button type="button" className="btn-primary monitor__save" onClick={() => void save()} disabled={!valid || saving}>
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </div>
  )
}

function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}
