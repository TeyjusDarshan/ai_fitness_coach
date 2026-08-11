import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { VideoPlaceholder } from '../components/VideoPlaceholder'
import { SetRow } from '../components/SetRow'
import { EffortSlider, DEFAULT_RPE } from '../components/EffortSlider'
import { useAppState } from '../state/AppStateContext'
import { logSet, logRpe } from '../api'
import { flattenExercises, targetReps, withRpeLogged, withSetLogged, withSetLogRemoved } from '../utils'
import { REST_BETWEEN_EXERCISES_SECONDS, REST_BETWEEN_SETS_SECONDS } from '../constants'
import type { ExerciseEntry } from '../types'

function initialRepCounts(exercise: ExerciseEntry | undefined): number[] {
  if (!exercise) return []
  const totalSets = exercise.sets ?? 0
  const fallback = targetReps(exercise)
  return Array.from({ length: totalSets }, (_, i) => {
    const log = exercise.set_logs.find((l) => l.set_number === i + 1)
    return log ? log.completed_reps : fallback
  })
}

export function ExerciseScreen() {
  const { dashboard, updateDashboard } = useAppState()
  const navigate = useNavigate()
  const { dayNumber, slotIndex } = useParams()
  const dayNum = Number(dayNumber)
  const slotIdx = Number(slotIndex)

  const day = dashboard?.days.find((d) => d.day_number === dayNum)
  const exercises = day ? flattenExercises(day) : []
  const exercise = exercises[slotIdx]

  // Locally-editable rep counts, re-seeded from the exercise's logged sets
  // whenever navigation lands on a different exercise (id changes) — the
  // +/- steppers stay instant/local until the user taps the tick to commit.
  const [repCounts, setRepCounts] = useState<number[]>(() => initialRepCounts(exercise))
  const [trackedExerciseId, setTrackedExerciseId] = useState<number | undefined>(exercise?.id)
  if (exercise && exercise.id !== trackedExerciseId) {
    setTrackedExerciseId(exercise.id)
    setRepCounts(initialRepCounts(exercise))
  }

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

  function handleRepChange(setIdx: number, reps: number) {
    setRepCounts((prev) => prev.map((v, i) => (i === setIdx ? reps : v)))
  }

  function handleConfirmSet(setIdx: number) {
    const setNumber = setIdx + 1
    const reps = repCounts[setIdx]
    const previousLog = exercise!.set_logs.find((l) => l.set_number === setNumber)

    const loggedSetNumbers = new Set(exercise!.set_logs.map((l) => l.set_number))
    loggedSetNumbers.add(setNumber)
    const willComplete = loggedSetNumbers.size >= (exercise!.sets ?? 0)

    updateDashboard((prev) => withSetLogged(prev, dayNum, exercise!.id, setNumber, reps))

    // Fire-and-forget: each set_number is its own row server-side, so a
    // concurrent in-flight confirm for a sibling set can't be clobbered by a
    // response snapshot that predates it. Not awaited, so confirming a set
    // can navigate to the between-set rest screen immediately.
    logSet(dashboard!.session_id, exercise!.id, setNumber, reps).catch(() => {
      updateDashboard((prev) =>
        previousLog
          ? withSetLogged(prev, dayNum, exercise!.id, setNumber, previousLog.completed_reps)
          : withSetLogRemoved(prev, dayNum, exercise!.id, setNumber),
      )
    })

    // Confirming a set that doesn't yet finish the exercise triggers a 1:30
    // rest before the next set; finishing the last set instead leaves the
    // user on "Begin Next Workout" to start the between-exercise rest.
    if (!willComplete) {
      navigate(restPath(REST_BETWEEN_SETS_SECONDS, `/day/${dayNum}/exercise/${slotIdx}`))
    }
  }

  function handleRpeChange(rpe: number) {
    const previousRpe = exercise!.rpe
    updateDashboard((prev) => withRpeLogged(prev, dayNum, exercise!.id, rpe))
    logRpe(dashboard!.session_id, exercise!.id, rpe).catch(() => {
      updateDashboard((prev) => withRpeLogged(prev, dayNum, exercise!.id, previousRpe))
    })
  }

  function handleBeginNext() {
    // If the user never touched the effort slider, log the Medium default
    // it's already displaying rather than leaving this exercise's RPE unset.
    if (exercise!.rpe == null) {
      handleRpeChange(DEFAULT_RPE)
    }

    const nextIndex = slotIdx + 1
    const next = nextIndex < exercises.length ? `/day/${dayNum}/exercise/${nextIndex}` : `/day/${dayNum}/summary`
    navigate(restPath(REST_BETWEEN_EXERCISES_SECONDS, next))
  }

  return (
    <div className="screen">
      <VideoPlaceholder />
      <h1 className="screen-title exercise-name">{exercise.name}</h1>

      <div className="card set-list">
        {repCounts.map((reps, i) => {
          const log = exercise.set_logs.find((l) => l.set_number === i + 1)
          return (
            <SetRow
              key={i}
              index={i}
              targetReps={exercise.reps}
              reps={reps}
              confirmed={log?.completed_reps === reps}
              onChange={(next) => handleRepChange(i, next)}
              onConfirm={() => handleConfirmSet(i)}
            />
          )
        })}
      </div>

      <EffortSlider rpe={exercise.rpe} onChange={handleRpeChange} />

      <button className="btn-primary begin-next-btn" onClick={handleBeginNext}>
        Begin Next Workout
      </button>
    </div>
  )
}
