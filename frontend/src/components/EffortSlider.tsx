// Simplified 3-point front end for the 1-10 RPE scale the backend stores —
// each label maps to a representative value rather than exposing all 10.
const LEVELS = [
  { label: 'Easy', rpe: 6 },
  { label: 'Medium', rpe: 8 },
  { label: 'Hard', rpe: 10 },
] as const

export const DEFAULT_RPE = LEVELS[1].rpe

function levelIndexForRpe(rpe: number | null): number {
  if (rpe == null) return 1
  let closest = 0
  for (let i = 1; i < LEVELS.length; i++) {
    if (Math.abs(LEVELS[i].rpe - rpe) < Math.abs(LEVELS[closest].rpe - rpe)) closest = i
  }
  return closest
}

interface Props {
  rpe: number | null
  onChange: (rpe: number) => void
}

export function EffortSlider({ rpe, onChange }: Props) {
  const index = levelIndexForRpe(rpe)

  return (
    <div className="effort-slider">
      <span className="effort-slider__title">How hard was this exercise?</span>
      <input
        type="range"
        className="effort-slider__input"
        min={0}
        max={LEVELS.length - 1}
        step={1}
        value={index}
        onChange={(e) => onChange(LEVELS[Number(e.target.value)].rpe)}
        aria-label="Exercise effort"
        aria-valuetext={LEVELS[index].label}
      />
      <div className="effort-slider__labels">
        {LEVELS.map((level, i) => (
          <span
            key={level.label}
            className={i === index ? 'effort-slider__label effort-slider__label--active' : 'effort-slider__label'}
          >
            {level.label}
          </span>
        ))}
      </div>
    </div>
  )
}
