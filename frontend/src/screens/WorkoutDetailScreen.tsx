import { useState } from 'react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { CardioDetails, LoggedSets, Prescription } from '../components/ExerciseLog'
import { Icon } from '../components/Icon'
import { Illustration } from '../components/Illustration'
import { PeriodPrompt } from '../components/PeriodPrompt'
import { VideoPlayer } from '../components/VideoPlayer'
import { useAppState } from '../state/AppStateContext'
import { useStartWorkout } from '../state/useStartWorkout'
import { WORKOUT_STATUS_LABELS, workoutDateLabel } from '../utils'
import { youtubeEmbedUrl, youtubeThumbnailUrl } from '../youtube'

// Read-only view of one workout panel: what's prescribed for a scheduled or
// missed workout, and what was logged set by set for a completed one.
export function WorkoutDetailScreen() {
  const { dashboard, pastWorkouts } = useAppState()
  const navigate = useNavigate()
  const { sessionId } = useParams()
  const { start, error, periodPrompt } = useStartWorkout()
  // The exercise whose demo video is open (one at a time).
  const [demoId, setDemoId] = useState<number | null>(null)

  if (!dashboard) return null
  // Older past workouts are only in the dashboard's "Load more" list.
  const workout = [...dashboard.workouts, ...pastWorkouts].find((w) => w.session_id === Number(sessionId))
  if (!workout) return <Navigate to="/" replace />

  const completed = workout.status === 'completed'

  return (
    <div className="screen workout-detail">
      <button className="back-link" onClick={() => navigate('/')}>
        <Icon name="chevronLeft" size={18} />
        Back
      </button>
      <div className="workout-detail__hero">
        <div>
          <h1 className="screen-title workout-detail__title">{workout.name}</h1>
          <p className="workout-detail__meta">
            <Icon name="calendar" size={16} />
            {WORKOUT_STATUS_LABELS[workout.status]} · {workoutDateLabel(workout)}
          </p>
        </div>
        <Illustration className="workout-detail__art" />
      </div>
      {error && <div className="error-banner">{error}</div>}

      {workout.cardio ? (
        <CardioDetails cardio={workout.cardio} completed={completed} />
      ) : (
        <div className="workout-detail__list">
          {workout.exercises.map((exercise, i) => (
            <div key={exercise.id} className="card workout-detail__exercise">
              <div className="workout-detail__row">
                <div className="workout-detail__thumb">
                  <img src={youtubeThumbnailUrl(exercise.video_url) ?? '/exercise-placeholder.jpg'} alt="" />
                  <span className={`workout-detail__number workout-detail__number--${exercise.category}`}>
                    {i + 1}
                  </span>
                </div>
                <div className="workout-detail__info">
                  <div className="workout-detail__name">{exercise.name}</div>
                  {exercise.skipped ? (
                    <div className="workout-detail__skipped">Skipped by your coach for this workout</div>
                  ) : (
                    <Prescription exercise={exercise} />
                  )}
                  {!exercise.skipped && exercise.video_url && youtubeEmbedUrl(exercise.video_url) && (
                    <button
                      type="button"
                      className="workout-detail__demo"
                      aria-expanded={demoId === exercise.id}
                      onClick={() => setDemoId(demoId === exercise.id ? null : exercise.id)}
                    >
                      <Icon name="play" size={14} />
                      {demoId === exercise.id ? 'Hide demo' : 'View demo'}
                    </button>
                  )}
                </div>
              </div>
              {demoId === exercise.id && (
                <div className="workout-detail__video">
                  <VideoPlayer videoUrl={exercise.video_url} autoplay />
                </div>
              )}
              {completed && !exercise.skipped && <LoggedSets exercise={exercise} />}
            </div>
          ))}
        </div>
      )}

      {workout.can_start && (
        <button className="btn-primary" onClick={() => void start(workout)}>
          <Icon name="play" size={18} />
          {workout.started_at ? 'Continue Workout' : 'Start Workout'}
        </button>
      )}
      <PeriodPrompt {...periodPrompt} />
    </div>
  )
}
