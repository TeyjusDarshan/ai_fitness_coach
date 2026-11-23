import { useState, type FormEvent } from 'react'
import { ApiError } from '../../api'
import { generateProfile, type ClientProfile, type ProfileResult } from '../../adminApi'
import { allTimezones, cleanWhatsAppNumber, isValidWhatsAppNumber, zoneForNumber } from '../../timezones'
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
  const [gender, setGender] = useState(result?.gender ?? '')
  const [whatsappNumber, setWhatsappNumber] = useState(result?.whatsapp_number ?? '')
  const [timezone, setTimezone] = useState(result?.timezone ?? '')
  // Until the coach picks a zone herself, it follows the number's country code.
  const [timezoneTouched, setTimezoneTouched] = useState(Boolean(result?.timezone))
  const [rawText, setRawText] = useState('')
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const userIdValid = USER_ID_PATTERN.test(userId.trim())
  const nameValid = name.trim() !== '' && name.trim().length <= MAX_NAME_LENGTH
  const numberValid = isValidWhatsAppNumber(whatsappNumber)
  const canGenerate =
    userIdValid && nameValid && gender !== '' && numberValid && timezone !== '' && rawText.trim() !== '' && !generating

  function changeUserId(value: string) {
    setUserId(value)
    // An Indian client's user id is usually her 10-digit number.
    if (!whatsappNumber && /^[0-9]{10}$/.test(value.trim())) changeNumber(`91${value.trim()}`)
  }

  function changeNumber(value: string) {
    setWhatsappNumber(value)
    if (!timezoneTouched) setTimezone(zoneForNumber(value) ?? '')
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!canGenerate) return
    setGenerating(true)
    setError(null)
    try {
      onGenerated(
        await generateProfile(
          adminKey,
          userId.trim(),
          name.trim(),
          gender,
          rawText,
          cleanWhatsAppNumber(whatsappNumber),
          timezone,
        ),
      )
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
            onChange={(e) => changeUserId(e.target.value)}
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
          <span>Gender</span>
          <select
            className="login-screen__input"
            value={gender}
            onChange={(e) => setGender(e.target.value)}
            disabled={generating}
          >
            <option value="" disabled>
              Select…
            </option>
            <option value="female">Female</option>
            <option value="male">Male</option>
            <option value="other">Other</option>
          </select>
          <small className="admin__hint">Women are asked if they are on their period before each workout.</small>
        </label>
        <label className="admin__field">
          <span>WhatsApp number</span>
          <input
            className="login-screen__input"
            value={whatsappNumber}
            onChange={(e) => changeNumber(e.target.value)}
            placeholder="Country code and number, e.g. 91 98765 43210"
            inputMode="tel"
            autoComplete="off"
            disabled={generating}
          />
          {whatsappNumber && !numberValid ? (
            <small className="admin__hint admin__hint--error">Include the country code, e.g. 91 for India.</small>
          ) : (
            <small className="admin__hint">How her WhatsApp messages are matched to her, and where reminders go.</small>
          )}
        </label>
        <label className="admin__field">
          <span>Time zone</span>
          <select
            className="login-screen__input"
            value={timezone}
            onChange={(e) => {
              setTimezone(e.target.value)
              setTimezoneTouched(true)
            }}
            disabled={generating}
          >
            <option value="" disabled>
              Select…
            </option>
            {allTimezones().map((zone) => (
              <option key={zone} value={zone}>
                {zone.replace(/_/g, ' ')}
              </option>
            ))}
          </select>
          <small className="admin__hint">Meal reminders go out at 11:00, 15:00 and 20:00 her time.</small>
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
