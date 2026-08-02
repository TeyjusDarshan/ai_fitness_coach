import { useNavigate, useParams } from 'react-router-dom'
import { VideoPlaceholder } from '../components/VideoPlaceholder'
import { SetRow } from '../components/SetRow'
import { VoiceNoteButton } from '../components/VoiceNoteButton'
import { useAppState } from '../state/AppStateContext'
import { toggleSet } from '../api'
import { flattenExercises, withSetToggled } from '../utils'
import { REST_BETWEEN_EXERCISES_SECONDS, REST_BETWEEN_SETS_SECONDS } from '../constants'

export function ExerciseScreen() {
  const { dashboard, updateDashboard } = useAppState()
  const navigate = useNavigate()
  const { dayNumber, slotIndex } = useParams()
  const dayNum = Number(dayNumber)
  const slotIdx = Number(slotIndex)

  const day = dashboard?.days.find((d) => d.day_number === dayNum)
  const exercises = day ? flattenExercises(day) : []
  const exercise = exercises[slotIdx]

  if (!dashboard || !day || !exercise) {
    return (
      <div className="screen">
        <div className="spinner" />
      </div>
    )
  }

  function restPath(seconds: number, next: string): string {
    return `/day/${dayNum}/rest?${new URLSearchParams({ seconds: String(seconds), next }).toString()}`
  }

  function handleToggle(setIdx: number, checked: boolean) {
    const previousValue = exercise.completed_sets[setIdx]
    const optimisticSets = exercise.completed_sets.map((v, i) => (i === setIdx ? checked : v))
    updateDashboard((prev) => withSetToggled(prev, dayNum, exercise.id, setIdx, checked))

    // Fire-and-forget: the atomic backend RPC confirms this index
    // specifically, so on failure we only need to revert this one index —
    // a concurrent in-flight toggle for a sibling index of this exercise
    // (e.g. two checkboxes tapped back to back) can't be clobbered by a
    // response snapshot that predates it. Not awaited, so checking a set
    // can navigate to the between-set rest screen immediately.
    toggleSet(dashboard!.session_id, exercise.id, setIdx, checked).catch(() => {
      updateDashboard((prev) => withSetToggled(prev, dayNum, exercise.id, setIdx, previousValue))
    })

    // Checking a set (not unchecking) that doesn't finish the exercise
    // triggers a 1:30 rest before the next set; the last set instead leaves
    // the user on "Begin Next Workout" to start the between-exercise rest.
    if (checked && !optimisticSets.every(Boolean)) {
      navigate(restPath(REST_BETWEEN_SETS_SECONDS, `/day/${dayNum}/exercise/${slotIdx}`))
    }
  }

  function handleBeginNext() {
    const nextIndex = slotIdx + 1
    const next = nextIndex < exercises.length ? `/day/${dayNum}/exercise/${nextIndex}` : `/day/${dayNum}/summary`
    navigate(restPath(REST_BETWEEN_EXERCISES_SECONDS, next))
  }

  return (
    <div className="screen">
      <VideoPlaceholder />
      <h1 className="screen-title exercise-name">{exercise.name}</h1>

      <div className="card set-list">
        {exercise.completed_sets.map((checked, i) => (
          <SetRow
            key={i}
            index={i}
            reps={exercise.reps}
            checked={checked}
            onToggle={(next) => handleToggle(i, next)}
          />
        ))}
      </div>

      <VoiceNoteButton />

      <button className="btn-primary begin-next-btn" onClick={handleBeginNext}>
        Begin Next Workout
      </button>
    </div>
  )
}
