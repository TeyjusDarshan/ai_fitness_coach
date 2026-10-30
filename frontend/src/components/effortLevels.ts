// Simplified 3-point front end for the 1-10 RPE scale the backend stores —
// each answer on the post-exercise feedback screen maps to a representative
// value rather than exposing all 10. `label` is the short form shown in
// workout history.
export const LEVELS = [
  { label: 'Easy', rpe: 6, title: 'Easier than expected', hint: 'I could have done more.', tone: 'easy' },
  { label: 'Medium', rpe: 8, title: 'About right', hint: 'Challenging but comfortable.', tone: 'about' },
  { label: 'Hard', rpe: 10, title: 'Too difficult', hint: 'I struggled to finish.', tone: 'hard' },
] as const

export type EffortTone = (typeof LEVELS)[number]['tone']

// "About right" — also what skipping the question logs.
export const DEFAULT_RPE = LEVELS[1].rpe

export function levelIndexForRpe(rpe: number | null): number {
  if (rpe == null) return 1
  let closest = 0
  for (let i = 1; i < LEVELS.length; i++) {
    if (Math.abs(LEVELS[i].rpe - rpe) < Math.abs(LEVELS[closest].rpe - rpe)) closest = i
  }
  return closest
}
