import { Icon } from './Icon'
import type { PlantLevel } from '../plant3d/levels'

interface Props {
  points: number
  plantLevel: PlantLevel
  // The caller animates `points` itself (grow screen), so the bar follows
  // without its own easing.
  instant?: boolean
}

/** "Level 3 · 75 / 100" with a progress bar towards the next plant stage. */
export function LevelCard({ points, plantLevel: { level, nextThreshold }, instant = false }: Props) {
  const fullyGrown = nextThreshold === null
  const percent = fullyGrown ? 100 : Math.round((points / nextThreshold) * 100)

  return (
    <div className={`level-card${instant ? ' level-card--instant' : ''}`}>
      <div className="level-card__head">
        <Icon name="leaf" size={26} className="level-card__icon" />
        <span className="level-card__level">{fullyGrown ? 'Fully grown' : `Level ${level}`}</span>
        <span className="level-card__points">{fullyGrown ? `${points} pts` : `${points} / ${nextThreshold}`}</span>
      </div>
      <div
        className="level-card__bar"
        role="progressbar"
        aria-label="Points towards the next plant level"
        aria-valuemin={0}
        aria-valuemax={nextThreshold ?? points}
        aria-valuenow={points}
      >
        <span className="level-card__fill" style={{ width: `${percent}%` }} />
      </div>
      <p className="level-card__tip">
        <Icon name="lightbulb" size={14} />
        Grow the plant using grow points · 1 workout = 25 points
      </p>
    </div>
  )
}
