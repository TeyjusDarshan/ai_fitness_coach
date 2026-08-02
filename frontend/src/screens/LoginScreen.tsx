import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAppState } from '../state/AppStateContext'

export function LoginScreen() {
  const { login, loading, error } = useAppState()
  const [username, setUsername] = useState('')
  const navigate = useNavigate()

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const trimmed = username.trim()
    if (!trimmed) return
    try {
      await login(trimmed)
      navigate('/', { replace: true })
    } catch {
      // error is already surfaced via useAppState().error
    }
  }

  return (
    <div className="screen login-screen">
      <div className="login-screen__brand">
        <div className="login-screen__logo" aria-hidden>🏋️</div>
        <h1 className="screen-title">AI Fitness Coach</h1>
        <p className="login-screen__subtitle">Enter your username to see your weekly plan.</p>
      </div>

      <form onSubmit={handleSubmit} className="login-screen__form">
        {error && <div className="error-banner">{error}</div>}
        <input
          className="login-screen__input"
          type="text"
          placeholder="Username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoCapitalize="none"
          autoCorrect="off"
          autoFocus
        />
        <button className="btn-primary" type="submit" disabled={loading || !username.trim()}>
          {loading ? 'Checking…' : 'Continue'}
        </button>
      </form>
    </div>
  )
}
