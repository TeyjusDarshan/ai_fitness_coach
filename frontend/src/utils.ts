import type { Dashboard, DashboardDay, ExerciseEntry } from './types'

export function flattenExercises(day: DashboardDay): ExerciseEntry[] {
  return [...day.primary, ...day.secondary]
}

export function isExerciseComplete(exercise: ExerciseEntry): boolean {
  return exercise.completed_sets.length > 0 && exercise.completed_sets.every(Boolean)
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

// Flips a single set index against whatever the array currently is in
// `dashboard` — safe to use for optimistic updates/reverts issued from a
// stale closure, since it never clobbers a sibling index's concurrent change.
export function withSetToggled(
  dashboard: Dashboard,
  dayNumber: number,
  exerciseId: number,
  setIndex: number,
  value: boolean,
): Dashboard {
  return mapExercise(dashboard, dayNumber, exerciseId, (ex) => ({
    ...ex,
    completed_sets: ex.completed_sets.map((v, i) => (i === setIndex ? value : v)),
  }))
}

export function capitalize(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}
