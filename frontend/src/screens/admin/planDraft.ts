import type {
  Category,
  ClientProfile,
  InitialPlanRequest,
  LibraryExercise,
  PlanTemplate,
  SlotTemplate,
} from '../../adminApi'

// The coach's in-progress plan: one SlotDraft per DAY_TEMPLATES slot, keyed
// by training day. Inputs stay strings until submit so half-typed numbers
// don't fight the user.

export const CATEGORIES: Category[] = ['primary', 'secondary']

// Same defaults the workout agent uses: 3 sets per primary slot, 2 per
// secondary, reps at the beginner anchor (25% into the rep range).
const DEFAULT_SETS: Record<Category, number> = { primary: 3, secondary: 2 }
const BEGINNER_REP_ANCHOR = 0.25
export const MAX_SETS = 10
export const MAX_REPS = 100

export interface SlotDraft {
  exerciseId: number | null
  sets: string
  reps: string
  note: string
}

export type DayDraft = Record<Category, SlotDraft[]>
export type PlanDraft = Record<number, DayDraft>

export function emptyDraft(template: PlanTemplate): PlanDraft {
  const draft: PlanDraft = {}
  for (const day of template.schedule) {
    if (day.is_rest_day) continue
    draft[day.day_number] = {
      primary: day.primary.map(() => emptySlot('primary')),
      secondary: day.secondary.map(() => emptySlot('secondary')),
    }
  }
  return draft
}

function emptySlot(category: Category): SlotDraft {
  return { exerciseId: null, sets: String(DEFAULT_SETS[category]), reps: '', note: '' }
}

export function defaultPlanType(templates: Record<string, PlanTemplate>, profile: ClientProfile): string {
  const types = Object.keys(templates)
  const days = profile.availability?.days_per_week
  if (days != null && days >= 4 && templates['4_day']) return '4_day'
  return templates['3_day'] ? '3_day' : types[0]
}

export function defaultReps(exercise: LibraryExercise): string {
  if (exercise.min_reps == null || exercise.max_reps == null) return ''
  return String(Math.round(exercise.min_reps + BEGINNER_REP_ANCHOR * (exercise.max_reps - exercise.min_reps)))
}

export function matchesSlot(exercise: LibraryExercise, slot: SlotTemplate): boolean {
  return (
    exercise.movement_type === slot.movement_type &&
    exercise.dominant === slot.dominant &&
    (slot.orientation == null || exercise.orientation === slot.orientation)
  )
}

export function isIntInRange(value: string, max: number): boolean {
  const n = Number(value)
  return value.trim() !== '' && Number.isInteger(n) && n >= 1 && n <= max
}

export function isSlotComplete(slot: SlotDraft): boolean {
  return slot.exerciseId != null && isIntInRange(slot.sets, MAX_SETS) && isIntInRange(slot.reps, MAX_REPS)
}

export function allSlots(draft: PlanDraft): SlotDraft[] {
  return Object.values(draft).flatMap((day) => [...day.primary, ...day.secondary])
}

export function isOutsideRepRange(exercise: LibraryExercise | undefined, reps: string): boolean {
  if (!exercise || exercise.min_reps == null || exercise.max_reps == null || reps === '') return false
  const n = Number(reps)
  return n < exercise.min_reps || n > exercise.max_reps
}

// pain_flags are free-form LLM output ("knee", "right_knee", "lower_back");
// loaded_joints come from the fixed joints table (ankle, knee, hip, spine,
// shoulder, elbow, wrist).
const PAIN_FLAG_ALIASES: Record<string, string> = { back: 'spine', neck: 'spine' }

export function painJoints(profile: ClientProfile): Set<string> {
  const joints = new Set<string>()
  for (const flag of profile.health?.pain_flags ?? []) {
    for (const word of flag.toLowerCase().split(/[^a-z]+/)) {
      if (word) joints.add(PAIN_FLAG_ALIASES[word] ?? word)
    }
  }
  return joints
}

export function painfulJointsFor(exercise: LibraryExercise, pain: Set<string>): string[] {
  return exercise.loaded_joints.filter((joint) => pain.has(joint))
}

export function toRequest(planType: string, coachNotes: string, draft: PlanDraft): InitialPlanRequest {
  const toEntry = (slot: SlotDraft) => ({
    exercise_id: slot.exerciseId as number,
    sets: Number(slot.sets),
    reps: Number(slot.reps),
    note: slot.note.trim() || null,
  })
  return {
    plan_type: planType,
    coach_notes: coachNotes.trim() || null,
    days: Object.entries(draft).map(([dayNumber, day]) => ({
      day_number: Number(dayNumber),
      primary: day.primary.map(toEntry),
      secondary: day.secondary.map(toEntry),
    })),
  }
}

export function humanize(value: string | null | undefined): string {
  return (value ?? '').replace(/_/g, ' ')
}
