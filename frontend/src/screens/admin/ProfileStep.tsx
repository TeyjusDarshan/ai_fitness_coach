import { useState, type FormEvent } from 'react'
import { ApiError } from '../../api'
import { generateProfile, type ClientProfile, type ProfileResult } from '../../adminApi'
import { humanize } from './planDraft'

const USER_ID_PATTERN = /^[A-Za-z0-9_.-]{1,64}$/
const MAX_NAME_LENGTH = 100

// Step 1: user id + client name + the coach's free-form notes ->
// preprocessor agent -> upserted user_profiles row.
export function ProfileStep({
  adminKey,
  result,
  onGenerated,
  onContinue,
  onUnauthorized,
}: {
  adminKey: string
  result: ProfileResult | null
  onGenerated: (result: ProfileResult) => void
  onContinue: () => void
  onUnauthorized: () => void
}) {
  const [userId, setUserId] = useState(result?.user_id ?? '')
  const [name, setName] = useState(result?.name ?? '')
  const [rawText, setRawText] = useState('')
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const userIdValid = USER_ID_PATTERN.test(userId.trim())
  const nameValid = name.trim() !== '' && name.trim().length <= MAX_NAME_LENGTH
  const canGenerate = userIdValid && nameValid && rawText.trim() !== '' && !generating

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!canGenerate) return
    setGenerating(true)
    setError(null)
    try {
      onGenerated(await generateProfile(adminKey, userId.trim(), name.trim(), rawText))
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onUnauthorized()
        return
      }
      setError(err instanceof Error ? err.message : 'Failed to generate the profile.')
    } finally {
      setGenerating(false)
    }
  }

  return (
    <>
      <form className="card admin__section" onSubmit={handleSubmit}>
        <h2 className="admin__section-title">1 · Client intake</h2>
        <label className="admin__field">
          <span>User ID</span>
          <input
            className="login-screen__input"
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            placeholder="e.g. usr_10235"
            autoCapitalize="none"
            autoCorrect="off"
            disabled={generating}
          />
          {userId && !userIdValid && (
            <small className="admin__hint admin__hint--error">Letters, digits, “_”, “-” or “.” only (max 64).</small>
          )}
        </label>
        <label className="admin__field">
          <span>Client name</span>
          <input
            className="login-screen__input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Lakshmi Narayanan"
            autoComplete="off"
            maxLength={MAX_NAME_LENGTH}
            disabled={generating}
          />
          <small className="admin__hint">Shown to the client in the app and on workout summaries.</small>
        </label>
        <label className="admin__field">
          <span>About the client</span>
          <textarea
            className="login-screen__input admin__textarea"
            rows={8}
            value={rawText}
            onChange={(e) => setRawText(e.target.value)}
            placeholder="Age, goals, training history, injuries, pain, availability, equipment…"
            disabled={generating}
          />
        </label>
        {error && <div className="error-banner">{error}</div>}
        <button className="btn-primary" type="submit" disabled={!canGenerate}>
          {generating ? 'Generating profile…' : result ? 'Re-generate profile' : 'Generate profile'}
        </button>
        {generating && <p className="admin__hint">This takes a few seconds.</p>}
      </form>

      {result && !generating && (
        <section className="card admin__section">
          <h2 className="admin__section-title">
            Profile for {result.name} ({result.user_id})
            <span className="admin__pill">{result.user_created ? 'new user' : 'updated'}</span>
          </h2>
          <ProfileSummary profile={result.profile} />
          <button className="btn-primary" type="button" onClick={onContinue}>
            Continue to planner
          </button>
        </section>
      )}
    </>
  )
}

export function ProfileSummary({ profile }: { profile: ClientProfile }) {
  const { demographics: demo, goals, experience, health, availability } = profile
  const rows: [string, string][] = [
    ['Client', [demo?.age && `${demo.age} y`, demo?.sex].filter(Boolean).join(', ')],
    ['Goals', [goals?.primary_goal, ...(goals?.secondary_goals ?? [])].filter(Boolean).map(humanize).join(', ')],
    ['Experience', [experience?.training_experience_level, experience?.current_activity_level].filter(Boolean).map(humanize).join(', ')],
    [
      'Availability',
      [
        availability?.days_per_week && `${availability.days_per_week} days/week`,
        availability?.session_duration_minutes && `${availability.session_duration_minutes} min`,
      ]
        .filter(Boolean)
        .join(', '),
    ],
    ['Equipment', (profile.equipment_access?.available_equipment ?? []).map(humanize).join(', ')],
    [
      'Conditions',
      (health?.conditions ?? [])
        .map((c) => [humanize(c.name), c.location && `(${humanize(c.location)})`, c.severity].filter(Boolean).join(' '))
        .join('; '),
    ],
    [
      'Past injuries',
      (health?.past_injuries ?? []).map((i) => [humanize(i.type), i.side, humanize(i.status)].filter(Boolean).join(', ')).join('; '),
    ],
    ['Pain', (health?.pain_flags ?? []).map(humanize).join(', ')],
    ['Avoid', (health?.movements_to_avoid ?? []).map(humanize).join(', ')],
  ]

  return (
    <>
      {health?.medical_clearance_obtained === false && (
        <div className="admin__warning">No medical clearance reported — the plan will carry a warning.</div>
      )}
      <dl className="admin__profile">
        {rows
          .filter(([, value]) => value)
          .map(([label, value]) => (
            <div key={label} className="admin__profile-row">
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
      </dl>
    </>
  )
}
