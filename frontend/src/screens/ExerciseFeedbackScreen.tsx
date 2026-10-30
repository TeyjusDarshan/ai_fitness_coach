import { useRef, useState } from 'react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { Icon } from '../components/Icon'
import { DEFAULT_RPE, LEVELS, type EffortTone } from '../components/effortLevels'
import { useAppState } from '../state/AppStateContext'
import { useVoiceRecorder } from '../state/useVoiceRecorder'
import { logRpe, uploadExerciseFeedbackAudio } from '../api'
import { afterExercisePath, flattenExercises, formatClock, withRpeLogged } from '../utils'

// After a rep exercise's sets: how it felt (logged as RPE 6 / 8 / 10,
// skipping logs 8) and an optional voice note for the coach, then on to the
// between-exercise rest or, after the last exercise, the cool-down.
export function ExerciseFeedbackScreen() {
  const { dashboard, updateDashboard } = useAppState()
  const navigate = useNavigate()
  const { dayNumber, slotIndex } = useParams()
  const dayNum = Number(dayNumber)
  const slotIdx = Number(slotIndex)

  const day = dashboard?.days.find((d) => d.day_number === dayNum)
  const exercises = day ? flattenExercises(day) : []
  const exercise = exercises[slotIdx]

  // Coming back to an exercise already rated shows that answer picked.
  const [picked, setPicked] = useState<number | null>(exercise?.rpe_logged ? exercise.rpe : null)
  // The voice note stays on the device until she moves on, then uploads.
  const recordingRef = useRef<Blob | null>(null)
  const recorder = useVoiceRecorder((recording) => {
    recordingRef.current = recording
  })
  const [saving, setSaving] = useState(false)
  const [saveFailed, setSaveFailed] = useState(false)

  if (day?.locked) return <Navigate to="/" replace />

  if (!dashboard || !day || !exercise) {
    return (
      <div className="screen">
        <div className="spinner" />
      </div>
    )
  }

  const isLast = slotIdx + 1 >= exercises.length
  const recording = recorder.phase === 'recording'

  function logEffort(rpe: number) {
    const previousRpe = exercise!.rpe
    const previousLogged = !!exercise!.rpe_logged
    updateDashboard((prev) => withRpeLogged(prev, dayNum, exercise!.id, rpe))
    logRpe(day!.session_id!, exercise!.id, rpe).catch(() => {
      updateDashboard((prev) => withRpeLogged(prev, dayNum, exercise!.id, previousRpe, previousLogged))
    })
  }

  function moveOn() {
    navigate(afterExercisePath(dayNum, slotIdx, exercises.length))
  }

  async function finish(rpe: number) {
    logEffort(rpe)
    const note = recordingRef.current
    if (!note) return moveOn()
    setSaving(true)
    setSaveFailed(false)
    try {
      await uploadExerciseFeedbackAudio(day!.session_id!, exercise!.id, note)
      moveOn()
    } catch {
      setSaveFailed(true)
      setSaving(false)
    }
  }

  function recordAgain() {
    recordingRef.current = null
    setSaveFailed(false)
    recorder.reset()
  }

  return (
    <div className="screen feedback-screen">
      <button className="feedback-screen__back" onClick={() => navigate(-1)} aria-label="Back">
        <Icon name="chevronLeft" size={24} />
      </button>

      <div className="feedback-screen__badge" aria-hidden>
        <span className="feedback-screen__rays feedback-screen__rays--left" />
        <span className="feedback-screen__check">
          <Icon name="check" size={44} />
        </span>
        <span className="feedback-screen__rays feedback-screen__rays--right" />
      </div>

      <h1 className="feedback-screen__title">How did this exercise feel today?</h1>

      <div className="feedback-screen__options" role="radiogroup" aria-label="How did this exercise feel?">
        {LEVELS.map((level) => (
          <button
            key={level.rpe}
            role="radio"
            aria-checked={picked === level.rpe}
            className={`feedback-option feedback-option--${level.tone}${picked === level.rpe ? ' feedback-option--selected' : ''}`}
            onClick={() => setPicked(level.rpe)}
          >
            <FeedbackFace tone={level.tone} />
            <span className="feedback-option__text">
              <span className="feedback-option__title">{level.title}</span>
              <span className="feedback-option__hint">{level.hint}</span>
            </span>
          </button>
        ))}
      </div>

      {recorder.supported && (
        <div className="feedback-voice">
          {recorder.phase === 'recorded' && recorder.playbackUrl ? (
            <div className="feedback-voice__recorded">
              <div className="feedback-voice__recorded-head">
                <span className="feedback-voice__done">
                  <Icon name="check" size={16} /> Voice note added
                </span>
                <button className="btn-link" onClick={recordAgain} disabled={saving}>
                  Re-record
                </button>
              </div>
              <audio className="feedback-voice__player" src={recorder.playbackUrl} controls />
            </div>
          ) : (
            <button
              className="feedback-voice__row"
              onClick={() => (recording ? recorder.stop() : void recorder.start())}
              aria-label={recording ? 'Stop recording' : 'Record a voice note'}
            >
              <span className={`feedback-voice__mic${recording ? ' feedback-voice__mic--live' : ''}`}>
                <Icon name={recording ? 'stop' : 'mic'} size={recording ? 20 : 26} />
              </span>
              <span className="feedback-voice__text">
                {recording ? (
                  <>
                    <span className="feedback-voice__title">Recording… {formatClock(recorder.seconds)}</span>
                    <span className="feedback-voice__hint">Tap to stop</span>
                  </>
                ) : (
                  <>
                    <span className="feedback-voice__title">Tell us more?</span>
                    <span className="feedback-voice__hint">Add a voice note (optional)</span>
                  </>
                )}
              </span>
            </button>
          )}
          {recorder.error && <p className="feedback-voice__error">{recorder.error}</p>}
        </div>
      )}

      {saveFailed ? (
        <div className="feedback-screen__failed" role="alert">
          Couldn&apos;t save your voice note.
          <button className="btn-link" onClick={moveOn}>
            Continue without it
          </button>
        </div>
      ) : (
        <button className="feedback-screen__skip" onClick={() => void finish(DEFAULT_RPE)} disabled={recording || saving}>
          Skip this time
        </button>
      )}

      <button
        className="btn-primary feedback-screen__next"
        disabled={picked === null || recording || saving}
        onClick={() => void finish(picked!)}
      >
        {saving ? (
          'Saving voice note…'
        ) : saveFailed ? (
          'Try again'
        ) : (
          <>
            {isLast ? 'Finish Workout' : 'Next Exercise'} <Icon name="chevronRight" size={18} />
          </>
        )}
      </button>
    </div>
  )
}

function FeedbackFace({ tone }: { tone: EffortTone }) {
  const mouth =
    tone === 'easy' ? 'M8 13.5c1 2 2.4 3 4 3s3-1 4-3' : tone === 'about' ? 'M8.5 15h7' : 'M8.5 16.5c1-1.4 2.2-2 3.5-2s2.5.6 3.5 2'
  return (
    <svg className="feedback-option__face" viewBox="0 0 24 24" width="44" height="44" aria-hidden>
      <circle cx="12" cy="12" r="12" fill="currentColor" />
      <circle cx="9" cy="9.5" r="1.3" fill="#fff" />
      <circle cx="15" cy="9.5" r="1.3" fill="#fff" />
      <path d={mouth} stroke="#fff" strokeWidth="1.7" fill="none" strokeLinecap="round" />
    </svg>
  )
}
