import { LEVELS, levelIndexForRpe } from './components/EffortSlider'
import { COACH_WHATSAPP_NUMBER, REST_BETWEEN_EXERCISES_SECONDS } from './constants'
import type {
  Dashboard,
  DashboardDay,
  DashboardWorkout,
  DayCompleteSummary,
  ExerciseEntry,
  WorkoutStatus,
} from './types'

export function flattenExercises(day: DashboardDay): ExerciseEntry[] {
  return [...day.primary, ...day.secondary]
}

export function isExerciseComplete(exercise: ExerciseEntry): boolean {
  return Boolean(exercise.sets) && exercise.set_logs.length >= (exercise.sets ?? 0)
}

// exercise.reps is either a single numeric target (e.g. "10", shared by
// every set) or a comma-separated per-set target list (e.g. "11,10,10")
// written once a progression is mid-ramp on one set ahead of the others —
// falls back to 8 reps (30 seconds for a timed exercise) for the rare case a
// value is missing or non-numeric.
export function targetRepsForSet(exercise: ExerciseEntry, setIndex: number): number {
  const values = (exercise.reps ?? '').split(',').map((v) => Number(v.trim()))
  const parsed = values[setIndex] ?? values[0]
  return Number.isFinite(parsed) && parsed > 0 ? parsed : exercise.is_time_based ? 30 : 8
}

// The unit an exercise's targets and logs are in.
export function repUnit(exercise: ExerciseEntry): string {
  return exercise.is_time_based ? 'sec' : 'reps'
}

// 75 -> "01:15"
export function formatClock(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds))
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

export function restPath(dayNumber: number, seconds: number, next: string): string {
  return `/day/${dayNumber}/rest?${new URLSearchParams({ seconds: String(seconds), next }).toString()}`
}

// Where to go once an exercise is finished: the between-exercise rest and
// then the next exercise, or — after the last one — straight into the
// cool-down (no rest timer), which leads on to the summary.
export function afterExercisePath(dayNumber: number, slotIndex: number, exerciseCount: number): string {
  const nextIndex = slotIndex + 1
  return nextIndex < exerciseCount
    ? restPath(dayNumber, REST_BETWEEN_EXERCISES_SECONDS, `/day/${dayNumber}/exercise/${nextIndex}`)
    : `/day/${dayNumber}/cooldown`
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
// sessions row if the coach forwards it along (the backend's WhatsApp webhook
// keys off "Session ID").
export function buildCoachShareMessage(
  day: DashboardDay,
  summary: DayCompleteSummary,
  clientName: string | null,
): string {
  const lines: string[] = [`*Workout Summary — ${day.day_label} (${day.split_name})*`]
  if (clientName) lines.push(`Client: ${capitalize(clientName)}`)
  lines.push(`Session ID: ${summary.session_id}`, `Day: ${day.day_number}`)
  lines.push(
    '',
    `Total Time: ${formatDuration(summary.total_time_seconds)}`,
    `Exercises Completed: ${summary.exercises_completed}/${summary.total_exercises}`,
    `Sets Completed: ${summary.sets_completed}/${summary.total_sets}`,
    '',
    '*Exercises:*',
  )

  flattenExercises(day).forEach((exercise, index) => {
    const unit = exercise.is_time_based ? ' sec' : ''
    const target = exercise.reps ? `${exercise.sets ?? '?'}x${exercise.reps}${unit}` : `${exercise.sets ?? '?'} sets`
    const loggedReps = [...exercise.set_logs]
      .sort((a, b) => a.set_number - b.set_number)
      .map((log) => log.completed_reps)
      .join(', ')
    lines.push(
      `${index + 1}. ${exercise.name} — ${target}`,
      `   ${exercise.is_time_based ? 'Held (sec)' : 'Logged reps'}: ${loggedReps || 'Not logged'}`,
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

// "2026-10-13" -> "Mon 13 Oct". Parsed as a local calendar date (not UTC
// midnight) so the weekday can't shift by a day in negative-offset zones.
export function formatDayDate(isoDate: string): string {
  const [year, month, day] = isoDate.split('-').map(Number)
  return new Date(year, month - 1, day).toLocaleDateString('en-GB', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  })
}

export const WORKOUT_STATUS_LABELS: Record<WorkoutStatus, string> = {
  completed: 'Completed',
  missed: 'Missed',
  scheduled: 'Scheduled',
}

// The only startable workout is today's, so can_start doubles as "is today".
export function workoutDateLabel(workout: DashboardWorkout): string {
  return workout.can_start ? 'Today' : formatDayDate(workout.date)
}
