import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { browserSupportsWebAuthn, browserSupportsWebAuthnAutofill } from '@simplewebauthn/browser'
import { fetchLoginOptions, passkeyErrorMessage, signInWithPasskey, type LoginOptions } from '../auth'
import { useAppState } from '../state/AppStateContext'

// Server-side challenges expire after 5 minutes; refresh a little before.
const OPTIONS_REFRESH_MS = 4 * 60 * 1000

export function LoginScreen() {
  const { completeSignIn } = useAppState()
  const navigate = useNavigate()
  const [options, setOptions] = useState<LoginOptions | null>(null)
  const [signingIn, setSigningIn] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const supported = browserSupportsWebAuthn()

  const loadOptions = useCallback(() => {
    fetchLoginOptions()
      .then(setOptions)
      .catch(() => setError('Could not reach the server. Check your connection and try again.'))
  }, [])

  const finishSignIn = useCallback(
    (userId: string) => {
      completeSignIn(userId)
      navigate('/', { replace: true })
    },
    [completeSignIn, navigate],
  )

  useEffect(() => {
    if (!supported) return
    loadOptions()
    const interval = setInterval(loadOptions, OPTIONS_REFRESH_MS)
    return () => clearInterval(interval)
  }, [supported, loadOptions])

  // Passkey suggestions in the username field's autofill (iOS 16+, Chrome on
  // Android). Uses its own challenge; a tap on the button below aborts it.
  useEffect(() => {
    if (!supported) return
    let cancelled = false
    browserSupportsWebAuthnAutofill().then(async (autofill) => {
      if (!autofill || cancelled) return
      try {
        const me = await signInWithPasskey(await fetchLoginOptions(), true)
        if (!cancelled) finishSignIn(me.user_id)
      } catch (e) {
        const message = passkeyErrorMessage(e)
        if (message && !cancelled) setError(message)
      }
    })
    return () => {
      cancelled = true
    }
  }, [supported, finishSignIn])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!options) return
    setSigningIn(true)
    setError(null)
    try {
      const me = await signInWithPasskey(options)
      finishSignIn(me.user_id)
    } catch (err) {
      setError(passkeyErrorMessage(err))
      // The challenge may have been used up; get a fresh one for a retry.
      setOptions(null)
      loadOptions()
    } finally {
      setSigningIn(false)
    }
  }

  return (
    <div className="screen login-screen">
      <div className="login-screen__brand">
        <div className="login-screen__logo" aria-hidden>🏋️</div>
        <h1 className="screen-title">AI Fitness Coach</h1>
        <p className="login-screen__subtitle">Sign in with your passkey to see your weekly plan.</p>
      </div>

      {!supported ? (
        <div className="error-banner">
          This browser doesn't support passkeys. Please update iOS/Android or open the app in Safari or Chrome.
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="login-screen__form">
          {error && <div className="error-banner">{error}</div>}
          <input
            className="login-screen__input"
            type="text"
            name="username"
            placeholder="Username"
            autoComplete="username webauthn"
            autoCapitalize="none"
            autoCorrect="off"
          />
          <button className="btn-primary" type="submit" disabled={!options || signingIn}>
            {signingIn ? 'Signing in…' : 'Sign in with passkey'}
          </button>
          <p className="login-screen__subtitle">
            New here? Open the sign-up link your coach sent you to create your passkey.
          </p>
        </form>
      )}
    </div>
  )
}
