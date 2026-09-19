import { LEVELS, levelIndexForRpe } from './components/EffortSlider'
import { COACH_WHATSAPP_NUMBER } from './constants'
import type { Dashboard, DashboardDay, DayCompleteSummary, ExerciseEntry } from './types'

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

function effortLabel(rpe: number | null): string {
  return rpe == null ? 'Not logged' : LEVELS[levelIndexForRpe(rpe)].label
}

// WhatsApp renders *text* as bold and a blank line as a paragraph break, so
// the message reads as formatted once pasted into a chat. Session ID/Day are
// included as plain labeled fields so the message can be parsed back to its
// session_exercises/session_day_logs rows if the coach forwards it along.
export function buildCoachShareMessage(
  day: DashboardDay,
  summary: DayCompleteSummary,
  username: string | null,
  sessionId: number,
): string {
  const lines: string[] = [`*Workout Summary — ${day.day_label} (${day.split_name})*`]
  if (username) lines.push(`Client: ${capitalize(username)}`)
  lines.push(`Session ID: ${sessionId}`, `Day: ${day.day_number}`)
  lines.push(
    '',
    `Total Time: ${formatDuration(summary.total_time_seconds)}`,
    `Exercises Completed: ${summary.exercises_completed}/${summary.total_exercises}`,
    `Sets Completed: ${summary.sets_completed}/${summary.total_sets}`,
    '',
    '*Exercises:*',
  )

  flattenExercises(day).forEach((exercise, index) => {
    const target = exercise.reps ? `${exercise.sets ?? '?'}x${exercise.reps}` : `${exercise.sets ?? '?'} sets`
    const loggedReps = [...exercise.set_logs]
      .sort((a, b) => a.set_number - b.set_number)
      .map((log) => log.completed_reps)
      .join(', ')
    lines.push(
      `${index + 1}. ${exercise.name} — ${target}`,
      `   Logged reps: ${loggedReps || 'Not logged'}`,
      `   Effort: ${effortLabel(exercise.rpe)}`,
    )
  })

  return lines.join('\n')
}

export function coachWhatsAppShareUrl(message: string): string {
  return `https://wa.me/${COACH_WHATSAPP_NUMBER}?text=${encodeURIComponent(message)}`
}

export function capitalize(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}
