import { useState } from 'react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { rateCardio } from '../api'
import { FeedbackFace } from '../components/FeedbackFace'
import { Icon } from '../components/Icon'
import { CARDIO_RATING_BY_TONE, LEVELS } from '../components/effortLevels'
import { useAppState } from '../state/AppStateContext'
import type { CardioRating } from '../types'

// After the cardio circuit: how did the whole session feel? Easy steps next
// week's cardio up, Hard steps it down, and About right holds it (two such
// weeks in a row step it up; a period day's answer doesn't count). Saved
// before the cool-down, after which the grow screen completes the session;
// skipping counts as About right.
export function CardioRatingScreen() {
  const { dashboard, updateDashboard } = useAppState()
  const navigate = useNavigate()
  const { dayNumber } = useParams()
  const dayNum = Number(dayNumber)
  const day = dashboard?.days.find((d) => d.day_number === dayNum)
  const [picked, setPicked] = useState<CardioRating | null>(day?.cardio?.rating ?? null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!day || day.kind !== 'cardio' || !day.session_id) return <Navigate to="/" replace />

  async function finish(rating: CardioRating) {
    setSaving(true)
    setError(null)
    try {
      await rateCardio(day!.session_id!, rating)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save your answer.')
      setSaving(false)
      return
    }
    updateDashboard((prev) => ({
      ...prev,
      days: prev.days.map((d) =>
        d.day_number === dayNum && d.cardio ? { ...d, cardio: { ...d.cardio, rating } } : d,
      ),
    }))
    navigate(`/day/${dayNum}/cooldown`, { replace: true })
  }

  return (
    <div className="screen feedback-screen">
      <div className="feedback-screen__badge" aria-hidden>
        <span className="feedback-screen__rays feedback-screen__rays--left" />
        <span className="feedback-screen__check">
          <Icon name="heart" size={40} />
        </span>
        <span className="feedback-screen__rays feedback-screen__rays--right" />
      </div>

      <h1 className="feedback-screen__title">Cardio done! How did it feel today?</h1>

      <div className="feedback-screen__options" role="radiogroup" aria-label="How did the cardio feel?">
        {LEVELS.map((level) => {
          const rating = CARDIO_RATING_BY_TONE[level.tone]
          return (
            <button
              key={rating}
              role="radio"
              aria-checked={picked === rating}
              className={`feedback-option feedback-option--${level.tone}${picked === rating ? ' feedback-option--selected' : ''}`}
              onClick={() => setPicked(rating)}
              disabled={saving}
            >
              <FeedbackFace tone={level.tone} />
              <span className="feedback-option__text">
                <span className="feedback-option__title">{level.title}</span>
                <span className="feedback-option__hint">{level.hint}</span>
              </span>
            </button>
          )
        })}
      </div>

      {error && (
        <p className="feedback-screen__failed" role="alert">
          {error}
        </p>
      )}

      <button className="feedback-screen__skip" onClick={() => void finish('medium')} disabled={saving}>
        Skip this time
      </button>

      <button
        className="btn-primary feedback-screen__next"
        disabled={picked === null || saving}
        onClick={() => void finish(picked!)}
      >
        {saving ? (
          'Saving…'
        ) : (
          <>
            Finish Workout <Icon name="chevronRight" size={18} />
          </>
        )}
      </button>
    </div>
  )
}
