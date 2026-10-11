import { useMemo, useState } from 'react'
import { ApiError } from '../../api'
import {
  createInitialPlan,
  type InitialPlanResult,
  type PlanBuilderOptions,
  type ProfileResult,
} from '../../adminApi'
import { ProfileSummary } from './ProfileStep'
import {
  CATEGORIES,
  dayDateIso,
  isOutsideRepRange,
  painfulJointsFor,
  toRequest,
  type PlanDraft,
} from './planDraft'
import { formatDayDate } from '../../utils'

// Step 3: read-only recap of the whole plan, then save it as the user's
// first session.
export function ReviewStep({
  adminKey,
  options,
  profile,
  pain,
  planType,
  draft,
  coachNotes,
  startDate,
  onBack,
  onSaved,
  onUnauthorized,
}: {
  adminKey: string
  options: PlanBuilderOptions
  profile: ProfileResult
  pain: Set<string>
  planType: string
  draft: PlanDraft
  coachNotes: string
  startDate: string
  onBack: () => void
  onSaved: (result: InitialPlanResult) => void
  onUnauthorized: () => void
}) {
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const template = options.templates[planType]
  const exercisesById = useMemo(() => new Map(options.exercises.map((ex) => [ex.id, ex])), [options.exercises])

  async function submit() {
    setSubmitting(true)
    setError(null)
    try {
      onSaved(await createInitialPlan(adminKey, profile.user_id, toRequest(planType, coachNotes, startDate, draft)))
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onUnauthorized()
        return
      }
      setError(err instanceof Error ? err.message : 'Failed to save the plan.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <section className="card admin__section">
        <h2 className="admin__section-title">3 · Review</h2>
        <p className="admin__muted">
          {template.label} for <strong>{profile.user_id}</strong>, starting{' '}
          <strong>{formatDayDate(startDate)}</strong>
        </p>
        <ProfileSummary profile={profile.profile} />
        {coachNotes.trim() && (
          <div className="admin__coach-notes">
            <strong>Coach notes</strong>
            <p>{coachNotes.trim()}</p>
          </div>
        )}
      </section>

      {template.schedule.map((day) =>
        day.is_rest_day ? (
          <div key={day.day_number} className="admin__rest-day">
            {day.day_label} · {formatDayDate(dayDateIso(startDate, day.day_number))} · Rest
          </div>
        ) : (
          <section key={day.day_number} className="card admin__section">
            <h2 className="admin__section-title">
              {day.day_label} · {formatDayDate(dayDateIso(startDate, day.day_number))}
              <span className="admin__muted">· {day.split_name}</span>
            </h2>
            <table className="admin__review-table">
              <thead>
                <tr>
                  <th>Slot</th>
                  <th>Exercise</th>
                  <th>Sets × reps</th>
                  <th>Range</th>
                </tr>
              </thead>
              <tbody>
                {CATEGORIES.flatMap((category) =>
                  day[category].map((slot, index) => {
                    const slotDraft = draft[day.day_number][category][index]
                    const exercise = exercisesById.get(slotDraft.exerciseId as number)
                    const painful = exercise ? painfulJointsFor(exercise, pain) : []
                    return (
                      <tr key={`${category}-${index}`}>
                        <td>
                          <span className={`admin__badge admin__badge--${category}`}>{category}</span>
                          {slot.slot}
                        </td>
                        <td>
                          {exercise?.name}
                          {painful.length > 0 && (
                            <span className="admin__hint admin__hint--warn"> ⚠ {painful.join(', ')}</span>
                          )}
                          {slotDraft.note.trim() && <div className="admin__hint">{slotDraft.note.trim()}</div>}
                        </td>
                        <td className={isOutsideRepRange(exercise, slotDraft.reps) ? 'admin__hint--warn' : ''}>
                          {slotDraft.sets} × {slotDraft.reps}
                        </td>
                        <td className="admin__muted">
                          {exercise?.min_reps != null && exercise?.max_reps != null
                            ? `${exercise.min_reps}–${exercise.max_reps}`
                            : '—'}
                        </td>
                      </tr>
                    )
                  }),
                )}
              </tbody>
            </table>
          </section>
        ),
      )}

      <div className="admin__footer">
        {error && <div className="error-banner">{error}</div>}
        <div className="admin__actions">
          <button type="button" className="btn-secondary" onClick={onBack} disabled={submitting}>
            Back to edit
          </button>
          <button type="button" className="btn-primary" onClick={submit} disabled={submitting}>
            {submitting ? 'Saving…' : 'Submit plan'}
          </button>
        </div>
      </div>
    </>
  )
}

export function PlanSavedCard({ result, onStartOver }: { result: InitialPlanResult; onStartOver: () => void }) {
  const [copied, setCopied] = useState(false)

  async function copyLink() {
    if (!result.enrollment) return
    try {
      await navigator.clipboard.writeText(result.enrollment.url)
      setCopied(true)
    } catch {
      // clipboard blocked; the link is still selectable below
    }
  }

  return (
    <section className="card admin__section">
      <h2 className="admin__section-title">Plan saved</h2>
      <p>
        <strong>{result.user_id}</strong>’s first plan is live as plan #{result.plan_id}.
      </p>
      {result.enrollment ? (
        <>
          <p className="admin__hint">
            Send this one-time sign-up link to the client. It expires{' '}
            {new Date(result.enrollment.expires_at).toLocaleString()}.
          </p>
          <code className="admin__link">{result.enrollment.url}</code>
          <button type="button" className="btn-primary" onClick={copyLink}>
            {copied ? 'Copied ✓' : 'Copy sign-up link'}
          </button>
        </>
      ) : (
        <p className="admin__hint">
          No sign-up link was created: either the client already has a passkey, or minting it failed. Use POST
          /api/admin/users/{result.user_id}/enrollment-link if they still need one.
        </p>
      )}
      <button type="button" className="btn-secondary" onClick={onStartOver}>
        Set up another client
      </button>
    </section>
  )
}
