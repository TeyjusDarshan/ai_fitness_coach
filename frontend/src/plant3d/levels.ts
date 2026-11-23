// Plant levels unlocked with workout points (the backend gives 25 per
// completed workout). Each level is one growth step of PottedPlant, so the
// plant is fully grown at its last step.

// PottedPlant's LAST_STEP — repeated rather than imported, so the dashboard
// doesn't pull three.js into the main bundle.
export const MAX_LEVEL = 11

/** Points level `n` costs on its own: 25 for levels 1–4, 50 for 5–8, 100 for 9–12, … */
export function levelCost(n: number): number {
  return 25 * 2 ** Math.floor((n - 1) / 4)
}

/** Total points needed to reach level `n`. */
export function levelThreshold(n: number): number {
  let total = 0
  for (let k = 1; k <= n; k++) total += levelCost(k)
  return total
}

export interface PlantLevel {
  level: number
  /** Total points the next level needs, or null once fully grown. */
  nextThreshold: number | null
}

export function levelForPoints(points: number): PlantLevel {
  let level = 0
  while (level < MAX_LEVEL && points >= levelThreshold(level + 1)) level++
  return { level, nextThreshold: level < MAX_LEVEL ? levelThreshold(level + 1) : null }
}

/** The name of each plant stage (level 0–11), matching what PottedPlant shows at that step. */
export const STAGE_NAMES = [
  'Empty Pot',
  'Seedling',
  'First Leaf',
  'Young Plant',
  'Leafy Plant',
  'Budding',
  'First Bloom',
  'New Buds',
  'Blooming',
  'Flowering Bush',
  'Butterfly Visit',
  'Fully Grown',
] as const

export function stageName(level: number): string {
  return STAGE_NAMES[Math.max(0, Math.min(MAX_LEVEL, level))]
}

// XP per completed workout (the backend's POINTS_PER_WORKOUT).
export const XP_PER_WORKOUT = 25

/** Progress towards the next stage: 0–100, and how many workouts it still needs (0 once fully grown). */
export function stageProgress(xp: number): { percent: number; workoutsLeft: number; next: string | null } {
  const { level, nextThreshold } = levelForPoints(xp)
  if (nextThreshold === null) return { percent: 100, workoutsLeft: 0, next: null }
  const from = levelThreshold(level)
  return {
    percent: Math.round(((xp - from) / (nextThreshold - from)) * 100),
    workoutsLeft: Math.ceil((nextThreshold - xp) / XP_PER_WORKOUT),
    next: stageName(level + 1),
  }
}
