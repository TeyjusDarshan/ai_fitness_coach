import { useEffect, useRef, useState } from 'react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { uploadFeedbackAudio } from '../api'
import { Icon } from '../components/Icon'
import { useAppState } from '../state/AppStateContext'
import { formatDuration } from '../utils'

// Stop on its own at this length, well under the 4 MB the server accepts.
const MAX_RECORDING_SECONDS = 180

// MediaRecorder's formats differ by browser: webm/ogg on Chrome and Firefox,
// mp4 on Safari. First one this browser can record wins.
const MIME_TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus']

type Phase = 'idle' | 'recording' | 'recorded' | 'uploading' | 'sent'

// After the congratulations screen: the client records a voice note about the
// session, listens back, and sends it to the coach (or skips).
export function FeedbackScreen() {
  const { dashboard, refreshDashboard } = useAppState()
  const navigate = useNavigate()
  const { dayNumber } = useParams()
  const dayNum = Number(dayNumber)
  const sessionId = dashboard?.days.find((d) => d.day_number === dayNum)?.session_id

  const [phase, setPhase] = useState<Phase>('idle')
  const [seconds, setSeconds] = useState(0)
  const [recording, setRecording] = useState<Blob | null>(null)
  const [playbackUrl, setPlaybackUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const recorder = useRef<MediaRecorder | null>(null)
  const stream = useRef<MediaStream | null>(null)
  const timer = useRef<number | null>(null)

  const supported = typeof MediaRecorder !== 'undefined' && !!navigator.mediaDevices?.getUserMedia

  function releaseMic() {
    if (timer.current !== null) window.clearInterval(timer.current)
    timer.current = null
    stream.current?.getTracks().forEach((track) => track.stop())
    stream.current = null
  }

  // Let go of the microphone if the user leaves mid-recording.
  useEffect(() => releaseMic, [])
  useEffect(() => () => {
    if (playbackUrl) URL.revokeObjectURL(playbackUrl)
  }, [playbackUrl])

  // Auto-stop at the length limit.
  useEffect(() => {
    if (phase === 'recording' && seconds >= MAX_RECORDING_SECONDS) stopRecording()
  }, [phase, seconds])

  async function startRecording() {
    setError(null)
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      setError('We could not use your microphone. Allow microphone access in your browser settings and try again.')
      return
    }
    const mimeType = MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type))
    const rec = new MediaRecorder(stream.current, mimeType ? { mimeType } : undefined)
    const chunks: Blob[] = []
    rec.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.push(e.data)
    }
    rec.onstop = () => {
      releaseMic()
      const blob = new Blob(chunks, { type: rec.mimeType || mimeType || 'audio/webm' })
      setRecording(blob)
      setPlaybackUrl(URL.createObjectURL(blob))
      setPhase('recorded')
    }
    recorder.current = rec
    rec.start()
    setSeconds(0)
    setPhase('recording')
    timer.current = window.setInterval(() => setSeconds((s) => s + 1), 1000)
  }

  function stopRecording() {
    if (recorder.current?.state === 'recording') recorder.current.stop()
  }

  function recordAgain() {
    setRecording(null)
    setPlaybackUrl(null)
    setPhase('idle')
  }

  async function send() {
    if (!recording || sessionId == null) return
    setPhase('uploading')
    setError(null)
    try {
      await uploadFeedbackAudio(sessionId, recording)
      setPhase('sent')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not send your recording. Please try again.')
      setPhase('recorded')
    }
  }

  async function backToDashboard() {
    try {
      await refreshDashboard()
    } catch {
      // The plan may have just completed; the dashboard screen handles it.
    }
    navigate('/', { replace: true })
  }

  if (!dashboard) return null
  if (sessionId == null) return <Navigate to="/" replace />

  return (
    <div className="screen feedback-screen">
      <div className="card feedback-card">
        <h1 className="feedback-card__title">How was your workout?</h1>
        <p className="feedback-card__text">
          Tell your coach in your own words — what felt good, what was hard, anything that hurt.
        </p>

        {!supported && (
          <div className="error-banner">Voice recording isn&apos;t available in this browser.</div>
        )}

        {phase === 'idle' && supported && (
          <button className="feedback-mic" onClick={() => void startRecording()} aria-label="Start recording">
            <Icon name="mic" size={40} />
          </button>
        )}
        {phase === 'idle' && supported && <p className="feedback-card__hint">Tap to start recording</p>}

        {phase === 'recording' && (
          <>
            <button className="feedback-mic feedback-mic--live" onClick={stopRecording} aria-label="Stop recording">
              <Icon name="stop" size={36} />
            </button>
            <p className="feedback-card__timer">{formatDuration(seconds)}</p>
            <p className="feedback-card__hint">Recording… tap to stop</p>
          </>
        )}

        {(phase === 'recorded' || phase === 'uploading') && playbackUrl && (
          <>
            <audio className="feedback-card__player" src={playbackUrl} controls />
            <button className="btn-primary" disabled={phase === 'uploading'} onClick={() => void send()}>
              {phase === 'uploading' ? 'Sending…' : 'Send to Coach'}
            </button>
            <button className="btn-secondary" disabled={phase === 'uploading'} onClick={recordAgain}>
              Record Again
            </button>
          </>
        )}

        {phase === 'sent' && (
          <>
            <div className="feedback-card__sent">
              <Icon name="check" size={28} />
              Thanks! Your feedback was sent.
            </div>
          </>
        )}

        {error && <div className="error-banner">{error}</div>}
      </div>

      <button className={phase === 'sent' ? 'btn-primary' : 'btn-secondary'} onClick={() => void backToDashboard()}>
        {phase === 'sent' ? 'Back to Dashboard' : 'Skip'}
      </button>
    </div>
  )
}
