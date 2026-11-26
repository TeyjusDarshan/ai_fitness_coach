// Shared helpers for the weight card and the Weight Trend screen.
import type { WeightOverview } from './types'

export function kg(value: number): string {
  return `${value.toFixed(1)} kg`
}

export function signedKg(value: number): string {
  const rounded = Math.round(value * 10) / 10
  return `${rounded > 0 ? '+' : rounded < 0 ? '−' : '±'}${Math.abs(rounded).toFixed(1)} kg`
}

// This week's average vs last week's, and whether it moved toward her goal
// (green) or away from it (grey; never red). Null until both weeks have one.
export function weekChange(weight: WeightOverview): { change: number; toward: boolean } | null {
  const now = weight.this_week.avg_kg
  const before = weight.last_week_avg_kg
  if (now === null || before === null) return null
  const change = Math.round((now - before) * 10) / 10
  let toward: boolean
  if (weight.goal === 'lose') toward = change < 0
  else if (weight.goal === 'gain') toward = change > 0
  else {
    const keep = weight.keep_kg ?? weight.start_kg
    toward = Math.abs(now - keep) <= Math.abs(before - keep) + 0.05
  }
  return { change, toward }
}

// The average the progress bar and gauge point at: this week's, or the
// last closed week's before she has sent any reading this week.
export function currentAverage(weight: WeightOverview): number | null {
  return weight.this_week.avg_kg ?? weight.weeks.at(-1)?.avg_kg ?? null
}

// How far along start → target (0–1).
export function progressFraction(weight: WeightOverview, average: number): number {
  if (weight.target_kg === null || weight.target_kg === weight.start_kg) return 0
  const f = (weight.start_kg - average) / (weight.start_kg - weight.target_kg)
  return Math.min(1, Math.max(0, f))
}

// The maintain band: ±2.5% of the weight she's keeping.
export const MAINTAIN_BAND = 0.025

export function maintainBand(weight: WeightOverview): { keep: number; low: number; high: number } {
  const keep = weight.keep_kg ?? weight.start_kg
  return { keep, low: keep * (1 - MAINTAIN_BAND), high: keep * (1 + MAINTAIN_BAND) }
}

// "16 நவ." for chart labels.
const SHORT_DATE = new Intl.DateTimeFormat('ta-IN', { day: 'numeric', month: 'short' })
export function shortTamilDate(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return SHORT_DATE.format(new Date(y, m - 1, d))
}
