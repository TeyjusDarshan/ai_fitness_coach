import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAppState } from '../state/AppStateContext'
import { completeSession, uploadFeedbackAudio } from '../api'
import { Icon } from '../components/Icon'
import { buildCoachShareMessage, capitalize, coachWhatsAppShareUrl, formatDuration } from '../utils'
import { useVoiceRecorder } from '../state/useVoiceRecorder'
import type { DayCompleteSummary } from '../types'

export function SummaryScreen() {
  const { dashboard, displayName, refreshDashboard } = useAppState()
  const navigate = useNavigate()
  const { dayNumber } = useParams()
  const dayNum = Number(dayNumber)

  const [summary, setSummary] = useState<DayCompleteSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const fired = useRef(false)

  // The voice note uploads as soon as recording stops, so the share tap can
  // open WhatsApp straight away (iOS blocks window.open after an await).
  const [upload, setUpload] = useState<'idle' | 'saving' | 'saved' | 'failed'>('idle')
  const sessionIdRef = useRef<number | null>(null)
  const recordingRef = useRef<Blob | null>(null)
  const uploadToken = useRef(0)

  async function saveRecording(recording: Blob) {
    const sessionId = sessionIdRef.current
    if (sessionId == null) return
    recordingRef.current = recording
    const token = ++uploadToken.current
    setUpload('saving')
    try {
      await uploadFeedbackAudio(sessionId, recording)
      if (token === uploadToken.current) setUpload('saved')
    } catch {
      if (token === uploadToken.current) setUpload('failed')
    }
  }

  const recorder = useVoiceRecorder((recording) => void saveRecording(recording))

  function recordAgain() {
    uploadToken.current++
    recordingRef.current = null
    setUpload('idle')
    recorder.reset()
  }

  useEffect(() => {
    if (fired.current || !dashboard) return
    const sessionId = dashboard.days.find((d) => d.day_number === dayNum)?.session_id
    if (sessionId == null) return
    fired.current = true
    completeSession(sessionId)
      .then((result) => {
        sessionIdRef.current = result.session_id
        setSummary(result)
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to complete this day.'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboard])

  async function handleBackToDashboard() {
    try {
      await refreshDashboard()
    } catch {
      // No unfinished session left to fetch — e.g. this was the plan's last
      // remaining day and it just auto-completed the whole plan. Navigate
      // anyway; the dashboard screen's own error state (with a "Sign out"
      // fallback) takes over from here.
    }
    navigate('/', { replace: true })
  }

  if (error) {
    return (
      <div className="screen">
        <div className="error-banner">{error}</div>
        <button className="btn-secondary" onClick={handleBackToDashboard}>
          Back to Dashboard
        </button>
      </div>
    )
  }

  if (!summary) {
    return (
      <div className="screen">
        <div className="spinner" />
      </div>
    )
  }

  const day = dashboard?.days.find((d) => d.day_number === dayNum)

  function handleShareWithCoach() {
    if (!day || !summary || !dashboard) return
    const message = buildCoachShareMessage(day, summary, displayName)
    window.open(coachWhatsAppShareUrl(message), '_blank', 'noopener,noreferrer')
  }

  return (
    <div className="screen summary-screen">
      <header className="summary-hero">
        <div className="summary-hero__trophy">
          <span className="summary-hero__confetti" aria-hidden>
            {Array.from({ length: 10 }, (_, i) => (
              <span key={i} className={`confetti confetti--${i}`} />
            ))}
          </span>
          <Laurel side="left" />
          <Trophy />
          <Laurel side="right" />
        </div>
        <h1 className="summary-hero__title">Workout Complete</h1>
        {summary.plan_completed && (
          <p className="summary-hero__plan-complete">You&apos;ve completed your whole plan!</p>
        )}
        <p className="summary-hero__greeting">Great job{displayName ? `, ${capitalize(displayName)}` : ''}!</p>
      </header>

      <section className="panel feedback-panel">
        <div className="panel__head">
          <span className="panel__badge">
            <Icon name="chat" size={26} />
          </span>
          <h2 className="panel__title">How did today&apos;s workout feel?</h2>
        </div>

        {!recorder.supported ? (
          <div className="error-banner">Voice recording isn&apos;t available in this browser.</div>
        ) : recorder.phase === 'recorded' && recorder.playbackUrl ? (
          <div className="recorded">
            <audio className="recorded__player" src={recorder.playbackUrl} controls />
            <div className="recorded__row">
              <span className={`recorded__status recorded__status--${upload}`}>
                {upload === 'saving' && 'Saving…'}
                {upload === 'saved' && (
                  <>
                    <Icon name="check" size={16} /> Voice note saved
                  </>
                )}
                {upload === 'failed' && "Couldn't save your voice note"}
              </span>
              {upload === 'failed' && (
                <button
                  className="btn-link"
                  onClick={() => recordingRef.current && void saveRecording(recordingRef.current)}
                >
                  Retry
                </button>
              )}
              <button className="btn-link" onClick={recordAgain} disabled={upload === 'saving'}>
                Record again
              </button>
            </div>
          </div>
        ) : (
          <div className="mic">
            <button
              className={`mic__button${recorder.phase === 'recording' ? ' mic__button--live' : ''}`}
              onClick={() => (recorder.phase === 'recording' ? recorder.stop() : void recorder.start())}
              aria-label={recorder.phase === 'recording' ? 'Stop recording' : 'Start recording'}
            >
              <Icon name={recorder.phase === 'recording' ? 'stop' : 'mic'} size={recorder.phase === 'recording' ? 34 : 40} />
            </button>
            {recorder.phase === 'recording' ? (
              <>
                <p className="mic__timer">{formatDuration(recorder.seconds)}</p>
                <p className="mic__hint">Recording… tap to stop</p>
              </>
            ) : (
              <p className="mic__label">Tap to Record</p>
            )}
          </div>
        )}
        {recorder.error && <div className="error-banner">{recorder.error}</div>}

        <p className="tip">
          <Icon name="lightbulb" size={20} />
          <span>
            <strong>Tip:</strong> Be honest — your coach is here to help!
          </span>
        </p>
      </section>

      <section className="panel workout-panel">
        <div className="workout-panel__head">
          <h2 className="workout-panel__title">
            <Icon name="dumbbell" size={22} />
            Today&apos;s Workout
          </h2>
          <button className="workout-panel__details" onClick={() => navigate(`/workout/${summary.session_id}`)}>
            View Details
            <Icon name="chevronRight" size={16} />
          </button>
        </div>
        <dl className="stats">
          <div className="stats__item">
            <span className="stats__badge">
              <Icon name="clock" size={22} />
            </span>
            <dd>{formatDuration(summary.total_time_seconds)}</dd>
            <dt>Duration</dt>
          </div>
          <div className="stats__item">
            <span className="stats__badge">
              <Icon name="layers" size={22} />
            </span>
            <dd>{summary.exercises_completed}</dd>
            <dt>Exercises</dt>
          </div>
          <div className="stats__item">
            <span className="stats__badge">
              <Icon name="layers" size={22} />
            </span>
            <dd>{summary.sets_completed}</dd>
            <dt>Sets</dt>
          </div>
        </dl>
      </section>

      {day && (
        <div className="share-cta">
          <button className="share-cta__button" disabled={upload === 'saving'} onClick={handleShareWithCoach}>
            <Icon name="send" size={24} />
            <span className="share-cta__text">
              <strong>Share Workout &amp; Voice Note</strong>
              <small>Sends your workout summary + voice feedback</small>
            </span>
          </button>
        </div>
      )}

      <button className="btn-secondary" onClick={handleBackToDashboard}>
        <Icon name="arrowLeft" size={20} />
        Back to Dashboard
      </button>
    </div>
  )
}

// A sprig of leaves either side of the trophy.
function Laurel({ side }: { side: 'left' | 'right' }) {
  return (
    <svg viewBox="0 0 30 60" className={`laurel laurel--${side}`} aria-hidden>
      <path d="M22 58C10 46 6 30 12 6" stroke="#5f9b78" strokeWidth="2.5" fill="none" strokeLinecap="round" />
      {[12, 24, 36, 48].map((y) => (
        <g key={y}>
          <ellipse cx={y < 30 ? 6 : 9} cy={y} rx="6" ry="3" transform={`rotate(-35 ${y < 30 ? 6 : 9} ${y})`} fill="#7fb38c" />
          <ellipse cx={y < 30 ? 17 : 21} cy={y - 4} rx="6" ry="3" transform={`rotate(35 ${y < 30 ? 17 : 21} ${y - 4})`} fill="#9cc49f" />
        </g>
      ))}
    </svg>
  )
}

// A gold cup with a star, between the laurels.
function Trophy() {
  return (
    <svg viewBox="0 0 80 84" className="trophy" aria-hidden>
      <path d="M40 2v6M24 6l3 5M56 6l-3 5" stroke="#f2b632" strokeWidth="3" strokeLinecap="round" />
      <path d="M20 22H9c0 11 5 17 14 18M60 22h11c0 11-5 17-14 18" stroke="#e2a62b" strokeWidth="5" fill="none" strokeLinecap="round" />
      <path d="M20 14h40v18a20 20 0 0 1-40 0V14Z" fill="#f6c84c" />
      <path d="M26 16h6v16a14 14 0 0 0 8 12.5A20 20 0 0 1 26 32V16Z" fill="#fff" opacity=".28" />
      <path d="m40 22 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2-4.5-4.4 6.2-.9L40 22Z" fill="#fff6d6" />
      <rect x="35" y="52" width="10" height="12" fill="#e2a62b" />
      <path d="M26 64h28l3 12H23l3-12Z" fill="#e2a62b" />
      <rect x="19" y="76" width="42" height="6" rx="3" fill="#cf9220" />
    </svg>
  )
}
