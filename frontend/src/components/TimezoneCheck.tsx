import { useState } from 'react'
import { useLocation } from 'react-router-dom'
import { updateMyTimezone } from '../auth'
import { useAppState } from '../state/AppStateContext'
import { cityOf, deviceTimezone, sameClock } from '../timezones'

// When she travels, her phone's clock moves to the new time zone by itself.
// If it no longer matches the one on file (user_profiles.timezone, which
// decides what "today" is for her food log and when meal reminders come),
// ask once whether to switch. "No" is remembered on this phone for that pair
// of zones, so she isn't asked again until either one changes.
const DECLINED_KEY = 'fc_timezone_declined'

function declinedPair(): string | null {
  try {
    return localStorage.getItem(DECLINED_KEY)
  } catch {
    return null
  }
}

function rememberDeclined(pair: string): void {
  try {
    localStorage.setItem(DECLINED_KEY, pair)
  } catch {
    // Private mode / blocked storage: she may be asked again next time.
  }
}

export function TimezoneCheck() {
  const { authStatus, dietEnabled, timezone, setTimezone } = useAppState()
  const [dismissed, setDismissed] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(false)
  const { pathname } = useLocation()

  const device = deviceTimezone()
  // Asked on the dashboard and the Food screens, never in the middle of a workout.
  const calmScreen = pathname === '/' || pathname.startsWith('/food')
  // Only clients with diet tracking: for now the time zone only affects food
  // dates and meal reminders (workouts still follow India time).
  if (authStatus !== 'signedIn' || !dietEnabled || !device || dismissed || !calmScreen) return null
  if (sameClock(device, timezone)) return null
  const pair = `${device}|${timezone}`
  if (declinedPair() === pair) return null

  async function switchZone() {
    if (!device) return
    setSaving(true)
    setError(false)
    try {
      const me = await updateMyTimezone(device)
      setTimezone(me.timezone || device)
      setDismissed(true)
    } catch {
      setError(true)
    } finally {
      setSaving(false)
    }
  }

  function keepZone() {
    rememberDeclined(pair)
    setDismissed(true)
  }

  const newCity = cityOf(device)
  const oldCity = cityOf(timezone)
  return (
    <div className="period-prompt period-prompt--center" role="dialog" aria-modal="true" aria-labelledby="tz-check-title">
      <div className="period-prompt__card">
        <div>
          <h2 id="tz-check-title" className="period-prompt__title">
            நீங்க இப்போ {newCity}-ல இருக்கீங்களா?
          </h2>
          <p className="period-prompt__text">
            உங்க phone-ல நேரம் {newCity} நேரத்துக்கு மாறியிருக்கு. உங்க சாப்பாடு பதிவும் நினைவூட்டல்களும் {newCity}{' '}
            நேரப்படி வரட்டுமா?
          </p>
          {error && <p className="period-prompt__text">மாத்த முடியல. மறுபடியும் முயற்சி பண்ணுங்க.</p>}
        </div>
        <div className="period-prompt__yes">
          <button
            className="period-prompt__btn period-prompt__btn--yes"
            disabled={saving}
            onClick={() => void switchZone()}
          >
            {saving ? '…' : `ஆமா, ${newCity} நேரம்`}
          </button>
        </div>
        <button className="period-prompt__btn period-prompt__btn--no" disabled={saving} onClick={keepZone}>
          இல்ல, {oldCity} நேரமே இருக்கட்டும்
        </button>
      </div>
    </div>
  )
}
