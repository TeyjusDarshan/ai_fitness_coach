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
