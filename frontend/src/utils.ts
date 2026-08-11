import type { Dashboard, DashboardDay, ExerciseEntry } from './types'

export function flattenExercises(day: DashboardDay): ExerciseEntry[] {
  return [...day.primary, ...day.secondary]
}

export function isExerciseComplete(exercise: ExerciseEntry): boolean {
  return Boolean(exercise.sets) && exercise.set_logs.length >= (exercise.sets ?? 0)
}

// exercise.reps is a plain numeric target (e.g. "10") set by the workout
// agent — falls back to 8 for the rare case it's missing or non-numeric.
export function targetReps(exercise: ExerciseEntry): number {
  const parsed = Number(exercise.reps)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 8
}

export function firstIncompleteIndex(day: DashboardDay): number {
  const exercises = flattenExercises(day)
  const idx = exercises.findIndex((ex) => !isExerciseComplete(ex))
  return idx === -1 ? 0 : idx
}

export function formatDuration(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}m ${seconds.toString().padStart(2, '0')}s`
}

function mapExercise(
  dashboard: Dashboard,
  dayNumber: number,
  exerciseId: number,
  fn: (ex: ExerciseEntry) => ExerciseEntry,
): Dashboard {
  return {
    ...dashboard,
    days: dashboard.days.map((d) =>
      d.day_number !== dayNumber
        ? d
        : {
            ...d,
            primary: d.primary.map((ex) => (ex.id === exerciseId ? fn(ex) : ex)),
            secondary: d.secondary.map((ex) => (ex.id === exerciseId ? fn(ex) : ex)),
          },
    ),
  }
}

// Upserts one set's logged rep count against whatever `dashboard` currently
// holds — safe for optimistic updates/reverts issued from a stale closure,
// since it never clobbers a sibling set_number's concurrent change.
export function withSetLogged(
  dashboard: Dashboard,
  dayNumber: number,
  exerciseId: number,
  setNumber: number,
  completedReps: number,
): Dashboard {
  return mapExercise(dashboard, dayNumber, exerciseId, (ex) => ({
    ...ex,
    set_logs: [...ex.set_logs.filter((log) => log.set_number !== setNumber), { set_number: setNumber, completed_reps: completedReps }],
  }))
}

// Reverts an optimistic log that was never actually confirmed by the server.
export function withSetLogRemoved(
  dashboard: Dashboard,
  dayNumber: number,
  exerciseId: number,
  setNumber: number,
): Dashboard {
  return mapExercise(dashboard, dayNumber, exerciseId, (ex) => ({
    ...ex,
    set_logs: ex.set_logs.filter((log) => log.set_number !== setNumber),
  }))
}

export function withRpeLogged(
  dashboard: Dashboard,
  dayNumber: number,
  exerciseId: number,
  rpe: number | null,
): Dashboard {
  return mapExercise(dashboard, dayNumber, exerciseId, (ex) => ({ ...ex, rpe }))
}

export function capitalize(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}
