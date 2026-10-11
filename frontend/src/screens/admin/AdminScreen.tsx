import { useEffect, useMemo, useRef, useState } from 'react'
import { ApiError } from '../../api'
import {
  fetchPlanBuilderOptions,
  readStoredAdminKey,
  storeAdminKey,
  type InitialPlanResult,
  type PlanBuilderOptions,
  type ProfileResult,
} from '../../adminApi'
import { defaultPlanType, emptyDraft, nextMondayIso, painJoints, type PlanDraft } from './planDraft'
import { PlannerStep } from './PlannerStep'
import { ProfileStep } from './ProfileStep'
import { PlanSavedCard, ReviewStep } from './ReviewStep'

// Coach-only onboarding: client notes -> generated profile -> hand-built
// plan -> review -> saved first session. Authorized by the admin key, not a
// passkey sign-in.

type Stage = 'profile' | 'planner' | 'review' | 'saved'

export function AdminScreen() {
  const [adminKey, setAdminKey] = useState(readStoredAdminKey)
  const [keyInput, setKeyInput] = useState('')
  const [options, setOptions] = useState<PlanBuilderOptions | null>(null)
  const [unlocking, setUnlocking] = useState(false)
  const [unlockError, setUnlockError] = useState<string | null>(null)

  async function unlock(key: string) {
    setUnlocking(true)
    setUnlockError(null)
    try {
      setOptions(await fetchPlanBuilderOptions(key))
      setAdminKey(key)
      storeAdminKey(key)
    } catch (e) {
      storeAdminKey(null)
      setAdminKey('')
      setUnlockError(e instanceof ApiError && e.status === 401 ? 'Wrong admin key.' : 'Could not load the exercise library.')
    } finally {
      setUnlocking(false)
    }
  }

  function lock(message: string | null = null) {
    storeAdminKey(null)
    setAdminKey('')
    setKeyInput('')
    setOptions(null)
    setUnlockError(message)
  }

  // Auto-unlock with a key remembered from earlier in this tab. The ref
  // keeps StrictMode's doubled effect from fetching twice.
  const triedStoredKey = useRef(false)
  useEffect(() => {
    if (triedStoredKey.current) return
    triedStoredKey.current = true
    if (adminKey) unlock(adminKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (!options) {
    if (adminKey && unlocking) {
      return (
        <div className="screen">
          <div className="spinner" />
        </div>
      )
    }
    return (
      <div className="screen login-screen">
        <div className="login-screen__brand">
          <div className="login-screen__logo" aria-hidden>
            📋
          </div>
          <h1 className="screen-title">Coach admin</h1>
          <p className="login-screen__subtitle">Enter the admin key to onboard a client.</p>
        </div>
        <form
          className="login-screen__form"
          onSubmit={(e) => {
            e.preventDefault()
            if (keyInput) unlock(keyInput)
          }}
        >
          {unlockError && <div className="error-banner">{unlockError}</div>}
          <input
            className="login-screen__input"
            type="password"
            placeholder="Admin key"
            autoComplete="off"
            value={keyInput}
            onChange={(e) => setKeyInput(e.target.value)}
          />
          <button className="btn-primary" type="submit" disabled={!keyInput || unlocking}>
            {unlocking ? 'Checking…' : 'Unlock'}
          </button>
        </form>
      </div>
    )
  }

  return (
    <OnboardingFlow
      adminKey={adminKey}
      options={options}
      onLock={() => lock()}
      onUnauthorized={() => lock('The admin key was rejected — enter it again.')}
    />
  )
}

function OnboardingFlow({
  adminKey,
  options,
  onLock,
  onUnauthorized,
}: {
  adminKey: string
  options: PlanBuilderOptions
  onLock: () => void
  onUnauthorized: () => void
}) {
  const [stage, setStage] = useState<Stage>('profile')
  const [profile, setProfile] = useState<ProfileResult | null>(null)
  const [planType, setPlanType] = useState(() => Object.keys(options.templates)[0])
  const [draft, setDraft] = useState<PlanDraft>(() => emptyDraft(options.templates[planType]))
  const [coachNotes, setCoachNotes] = useState('')
  const [startDate, setStartDate] = useState(nextMondayIso)
  const [saved, setSaved] = useState<InitialPlanResult | null>(null)
  const pain = useMemo(() => (profile ? painJoints(profile.profile) : new Set<string>()), [profile])

  function handleProfileGenerated(result: ProfileResult) {
    // A new client starts from a blank plan sized to their availability; a
    // re-generated profile for the same client keeps the picks so far.
    if (result.user_id !== profile?.user_id) {
      const type = defaultPlanType(options.templates, result.profile)
      setPlanType(type)
      setDraft(emptyDraft(options.templates[type]))
      setCoachNotes('')
      setStartDate(nextMondayIso())
    }
    setProfile(result)
  }

  function startOver() {
    setProfile(null)
    setSaved(null)
    setCoachNotes('')
    setStartDate(nextMondayIso())
    setDraft(emptyDraft(options.templates[planType]))
    setStage('profile')
  }

  useEffect(() => {
    window.scrollTo(0, 0)
  }, [stage])

  return (
    <div className="screen admin">
      <div className="admin__header">
        <h1 className="screen-title">Coach admin</h1>
        <button type="button" className="btn-link" onClick={onLock}>
          Lock
        </button>
      </div>
      <ol className="admin__steps">
        {(['profile', 'planner', 'review'] as const).map((s, i) => (
          <li key={s} className={stage === s ? 'admin__step--active' : ''}>
            {i + 1}. {s === 'profile' ? 'Client' : s === 'planner' ? 'Plan' : 'Review'}
          </li>
        ))}
      </ol>

      {stage === 'profile' && (
        <ProfileStep
          adminKey={adminKey}
          result={profile}
          onGenerated={handleProfileGenerated}
          onContinue={() => setStage('planner')}
          onUnauthorized={onUnauthorized}
        />
      )}
      {stage === 'planner' && profile && (
        <PlannerStep
          options={options}
          pain={pain}
          planType={planType}
          draft={draft}
          coachNotes={coachNotes}
          startDate={startDate}
          onStartDateChange={setStartDate}
          onPlanTypeChange={(type, next) => {
            setPlanType(type)
            setDraft(next)
          }}
          onDraftChange={setDraft}
          onCoachNotesChange={setCoachNotes}
          onBack={() => setStage('profile')}
          onReview={() => setStage('review')}
        />
      )}
      {stage === 'review' && profile && (
        <ReviewStep
          adminKey={adminKey}
          options={options}
          profile={profile}
          pain={pain}
          planType={planType}
          draft={draft}
          coachNotes={coachNotes}
          startDate={startDate}
          onBack={() => setStage('planner')}
          onSaved={(result) => {
            setSaved(result)
            setStage('saved')
          }}
          onUnauthorized={onUnauthorized}
        />
      )}
      {stage === 'saved' && saved && <PlanSavedCard result={saved} onStartOver={startOver} />}
    </div>
  )
}
