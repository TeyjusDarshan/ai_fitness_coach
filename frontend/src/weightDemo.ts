// TEMPORARY dummy weight data until GET /api/users/<id>/weight exists.
// Pick a scenario with ?weight=lose|gain|maintain|new|notoday in the URL
// (remembered for the session); lose is the default.
import type { WeightGoal, WeightOverview, WeightWeek } from './types'

type Scenario = 'lose' | 'gain' | 'maintain' | 'new' | 'notoday'
const SCENARIOS: Scenario[] = ['lose', 'gain', 'maintain', 'new', 'notoday']
const KEY = 'fc_weight_demo'

function scenario(): Scenario {
  const asked = new URLSearchParams(window.location.search).get('weight') as Scenario | null
  try {
    if (asked && SCENARIOS.includes(asked)) sessionStorage.setItem(KEY, asked)
    const kept = sessionStorage.getItem(KEY) as Scenario | null
    if (kept && SCENARIOS.includes(kept)) return kept
  } catch {
    if (asked && SCENARIOS.includes(asked)) return asked
  }
  return 'lose'
}

function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

function mondayOf(iso: string): string {
  const weekday = (new Date(`${iso}T00:00:00Z`).getUTCDay() + 6) % 7
  return addDays(iso, -weekday)
}

const round1 = (n: number) => Math.round(n * 10) / 10

// Closed weeks ending last week, oldest first, from a list of averages.
function weeksFrom(thisMonday: string, averages: number[], periodAt: number[] = []): WeightWeek[] {
  return averages.map((avg, i) => ({
    week_start: addDays(thisMonday, -7 * (averages.length - i)),
    avg_kg: avg,
    readings: 5 + (i % 3),
    period_week: periodAt.includes(i),
  }))
}

export function demoWeight(today: string): WeightOverview {
  const which = scenario()
  const monday = mondayOf(today)
  const daysIn = Math.round((Date.parse(today) - Date.parse(monday)) / 86_400_000) + 1

  if (which === 'new') {
    // Started this week: three readings so far, nothing closed yet.
    return {
      goal: 'lose',
      today: { date: today, weight_kg: 73.1 },
      this_week: { week_start: monday, avg_kg: 73.2, readings: Math.min(3, daysIn) },
      last_week_avg_kg: null,
      start_kg: 73.4,
      target_kg: 68,
      keep_kg: null,
      weeks: [],
      calorie_changes: [],
      status: null,
      readings_needed: 4 - Math.min(3, daysIn),
    }
  }

  const goal: WeightGoal = which === 'gain' || which === 'maintain' ? which : 'lose'
  if (goal === 'gain') {
    const averages = [48.2, 48.3, 48.5, 48.5, 48.6, 48.9, 49.1, 49.2, 49.4, 49.6]
    const weeks = weeksFrom(monday, averages, [3])
    return {
      goal,
      today: { date: today, weight_kg: 49.9 },
      this_week: { week_start: monday, avg_kg: 49.8, readings: Math.min(4, daysIn) },
      last_week_avg_kg: 49.6,
      start_kg: 48.0,
      target_kg: 52.0,
      keep_kg: null,
      weeks,
      calorie_changes: [{ date: weeks[5].week_start, from_kcal: 1850, to_kcal: 2000 }],
      status: 'on_track',
      readings_needed: 0,
    }
  }
  if (goal === 'maintain') {
    const averages = [62.1, 62.0, 62.3, 62.2, 62.4, 62.6, 62.5, 62.3, 62.4, 62.2, 62.3, 62.5]
    return {
      goal,
      today: { date: today, weight_kg: 62.6 },
      this_week: { week_start: monday, avg_kg: 62.4, readings: Math.min(5, daysIn) },
      last_week_avg_kg: 62.5,
      start_kg: 62.0,
      target_kg: null,
      keep_kg: 62.0,
      weeks: weeksFrom(monday, averages, [2, 6, 10]),
      calorie_changes: [],
      status: 'in_range',
      readings_needed: 0,
    }
  }

  // Lose (and "notoday": the same client before this morning's reading).
  const averages = [
    73.0, 72.8, 72.5, 72.3, 72.2, 71.9, 71.8, 71.8, 71.7, 71.4, 71.1, 70.9, 70.8, 70.6, 70.4,
  ].map(round1)
  const weeks = weeksFrom(monday, averages, [4, 8, 12])
  return {
    goal,
    today: which === 'notoday' ? null : { date: today, weight_kg: 70.2 },
    this_week: { week_start: monday, avg_kg: 70.3, readings: Math.min(which === 'notoday' ? 3 : 4, daysIn) },
    last_week_avg_kg: 70.4,
    start_kg: 73.0,
    target_kg: 68.0,
    keep_kg: null,
    weeks,
    calorie_changes: [{ date: weeks[8].week_start, from_kcal: 1600, to_kcal: 1500 }],
    status: 'on_track',
    readings_needed: 0,
  }
}
