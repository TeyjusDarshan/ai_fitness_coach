import { useEffect, useState } from 'react'
import {
  acceptSuggestion,
  fetchSuggestions,
  rejectSuggestion,
  requestSuggestions,
  type AppliedExerciseChange,
  type ExerciseSuggestion,
  type SuggestionAction,
  type SuggestionPrescription,
  type SuggestionRun,
} from '../../adminApi'
import { ApiError } from '../../api'

const ACTION_LABELS: Record<SuggestionAction, string> = {
  keep: 'Keep',
  adjust: 'Adjust',
  progress: 'Progress',
  regress: 'Regress',
  skip: 'Skip today',
}

const SOURCE_LABELS: Record<string, string> = {
  client_answer: 'Her answer',
  client_comment: 'Her words',
  set_logs: 'Set logs',
  rpe: 'Effort',
  joint_pain: 'Joint pain',
  profile: 'Profile',
  coach_note: 'Coach note',
  progression_rule: 'Progression rule',
}

const STATUS_LABELS: Partial<Record<ExerciseSuggestion['status'], string>> = {
  accepted: 'Accepted',
  rejected: 'Rejected',
  superseded: 'Replaced by a newer run',
}

function prescription(p: SuggestionPrescription): string {
  const unit = p.is_time_based ? ' s' : ''
  const reps = p.reps ? p.reps.replace(/,/g, ', ') : '—'
  const range = p.rep_range ? ` (range ${p.rep_range}${unit})` : ''
  return `${p.sets ?? '—'} sets × ${reps}${unit}${range}`
}

// The AI Coach's per-exercise suggestions for one upcoming workout, with
// one-click accept/reject. Accepting applies the change to the workout (via
// the server) and reports it through onApplied so the card updates in place.
export function CoachSuggestions({
  sessionId,
  adminKey,
  onUnauthorized,
  onApplied,
}: {
  sessionId: number
  adminKey: string
  onUnauthorized: () => void
  onApplied: (change: AppliedExerciseChange) => void
}) {
  const [data, setData] = useState<SuggestionRun | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [busy, setBusy] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  function handleError(err: unknown, fallback: string) {
    if (err instanceof ApiError && err.status === 401) onUnauthorized()
    else setError(err instanceof Error ? err.message : fallback)
  }

  useEffect(() => {
    let cancelled = false
    fetchSuggestions(adminKey, sessionId)
      .then((result) => !cancelled && setData(result))
      .catch((err) => !cancelled && handleError(err, 'Could not load the AI suggestions.'))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adminKey, sessionId])

  async function run() {
    setRunning(true)
    setError(null)
    try {
      setData(await requestSuggestions(adminKey, sessionId))
    } catch (err) {
      handleError(err, 'The AI coach could not finish. Try again.')
    } finally {
      setRunning(false)
    }
  }

  function setStatus(id: number, status: ExerciseSuggestion['status']) {
    setData((prev) =>
      prev && { ...prev, suggestions: prev.suggestions.map((s) => (s.id === id ? { ...s, status } : s)) },
    )
  }

  async function decide(suggestion: ExerciseSuggestion, accept: boolean) {
    setBusy(suggestion.id)
    setError(null)
    try {
      if (accept) {
        const result = await acceptSuggestion(adminKey, suggestion.id)
        setStatus(suggestion.id, 'accepted')
        onApplied(result.exercise)
      } else {
        await rejectSuggestion(adminKey, suggestion.id)
        setStatus(suggestion.id, 'rejected')
      }
    } catch (err) {
      handleError(err, 'Could not save that decision.')
    } finally {
      setBusy(null)
    }
  }

  const hasRun = Boolean(data?.run)
  const pending = data?.suggestions.filter((s) => s.status === 'pending').length ?? 0

  return (
    <div className="coach-ai">
      <div className="coach-ai__head">
        <div className="monitor__label">AI coach</div>
        <button className="btn-secondary coach-ai__run" disabled={running || loading} onClick={() => void run()}>
          {running ? 'Reviewing… (up to a minute)' : hasRun ? 'Ask again' : 'Get AI suggestions'}
        </button>
      </div>
      {error && <div className="admin__hint admin__hint--error">{error}</div>}
      {loading && <p className="admin__muted">Loading…</p>}
      {hasRun && data && (
        <>
          {data.run?.overview && <p className="coach-ai__overview">{data.run.overview}</p>}
          {pending > 0 && <p className="admin__muted">{pending} suggestion{pending === 1 ? '' : 's'} to review.</p>}
          <div className="coach-ai__list">
            {data.suggestions.map((s) => (
              <SuggestionRow
                key={s.id}
                suggestion={s}
                busy={busy === s.id}
                onAccept={() => void decide(s, true)}
                onReject={() => void decide(s, false)}
              />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function SuggestionRow({
  suggestion: s,
  busy,
  onAccept,
  onReject,
}: {
  suggestion: ExerciseSuggestion
  busy: boolean
  onAccept: () => void
  onReject: () => void
}) {
  const isChange = s.status !== 'no_change'
  return (
    <div className={`coach-ai__item coach-ai__item--${s.action} coach-ai__item--${s.status}`}>
      <div className="coach-ai__item-head">
        <span className="coach-ai__name">{s.current.name}</span>
        <span className={`coach-ai__badge coach-ai__badge--${s.action}`}>
          {isChange ? ACTION_LABELS[s.action] : 'No change'}
        </span>
      </div>

      <div className="coach-ai__change">
        <span>{prescription(s.current)}</span>
        {s.proposed && (
          <>
            <span className="coach-ai__arrow">→</span>
            <span className="coach-ai__proposed">
              {s.proposed.exercise_id !== s.current.exercise_id && <strong>{s.proposed.name}: </strong>}
              {prescription(s.proposed)}
            </span>
          </>
        )}
        {s.action === 'skip' && isChange && (
          <>
            <span className="coach-ai__arrow">→</span>
            <span className="coach-ai__proposed">Skipped for this workout only</span>
          </>
        )}
      </div>

      <p className="coach-ai__reason">{s.reason}</p>

      {s.evidence.length > 0 && (
        <ul className="coach-ai__evidence">
          {s.evidence.map((e, i) => (
            <li key={i}>
              <span className={`coach-ai__source${e.verified ? ' coach-ai__source--verified' : ''}`}>
                {SOURCE_LABELS[e.source] ?? e.source}
              </span>
              <span className="coach-ai__quote">{e.verified ? `“${e.quote}”` : e.quote}</span>
            </li>
          ))}
        </ul>
      )}

      {s.status === 'pending' ? (
        <div className="coach-ai__actions">
          <button className="btn-link" disabled={busy} onClick={onReject}>
            Reject
          </button>
          <button className="btn-primary coach-ai__accept" disabled={busy} onClick={onAccept}>
            {busy ? 'Saving…' : 'Accept'}
          </button>
        </div>
      ) : (
        STATUS_LABELS[s.status] && (
          <div className={`coach-ai__decided coach-ai__decided--${s.status}`}>{STATUS_LABELS[s.status]}</div>
        )
      )}
    </div>
  )
}
