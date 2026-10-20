import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { browserSupportsWebAuthn } from '@simplewebauthn/browser'
import { ApiError } from '../api'
import { enrollPasskey, fetchRegistrationOptions, passkeyErrorMessage, type RegistrationOptions } from '../auth'
import { Illustration } from '../components/Illustration'
import { useAppState } from '../state/AppStateContext'

const INVALID_LINK_MESSAGE = 'This sign-up link is invalid or has expired. Ask your coach for a new one.'

export function EnrollScreen() {
  const { completeSignIn } = useAppState()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')
  const supported = browserSupportsWebAuthn()

  const [options, setOptions] = useState<RegistrationOptions | null>(null)
  const [linkInvalid, setLinkInvalid] = useState(!token)
  const [enrolling, setEnrolling] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Fetching options also validates the link, so a dead link is reported
  // before the user taps anything.
  const loadOptions = useCallback(() => {
    if (!token) return
    fetchRegistrationOptions(token)
      .then(setOptions)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 400) setLinkInvalid(true)
        else setError('Could not reach the server. Check your connection and try again.')
      })
  }, [token])

  useEffect(() => {
    if (supported) loadOptions()
  }, [supported, loadOptions])

  async function handleCreatePasskey() {
    if (!token || !options) return
    setEnrolling(true)
    setError(null)
    try {
      const me = await enrollPasskey(token, options)
      completeSignIn(me.user_id)
      navigate('/', { replace: true })
    } catch (e) {
      setError(passkeyErrorMessage(e))
      setOptions(null)
      loadOptions()
    } finally {
      setEnrolling(false)
    }
  }

  let body
  if (!supported) {
    body = (
      <div className="error-banner">
        This browser doesn't support passkeys. Please update iOS/Android or open this link in Safari or Chrome.
      </div>
    )
  } else if (linkInvalid) {
    body = <div className="error-banner">{INVALID_LINK_MESSAGE}</div>
  } else {
    body = (
      <div className="login-screen__form">
        {error && <div className="error-banner">{error}</div>}
        <button className="btn-primary" onClick={handleCreatePasskey} disabled={!options || enrolling}>
          {enrolling ? 'Creating passkey…' : 'Create passkey'}
        </button>
      </div>
    )
  }

  return (
    <div className="screen login-screen">
      <div className="login-screen__brand">
        <Illustration className="login-screen__art" />
        <h1 className="screen-title">Set up sign-in</h1>
        <p className="login-screen__subtitle">
          Create a passkey to sign in with Face ID, Touch ID or your fingerprint — no password needed.
        </p>
      </div>
      {body}
    </div>
  )
}
