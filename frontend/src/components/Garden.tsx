import { lazy } from 'react'
import { stageName, stageProgress } from '../plant3d/levels'
import { Icon } from './Icon'

// The 3D plant carries three.js, so it loads on its own after the page.
export const LazyPlantCanvas = lazy(() => import('./PlantCanvas'))

// Falling petals: [left %, delay s, duration s, colour, size px].
const PETALS: [number, number, number, string, number][] = [
  [8, 0, 9, '#f6a5c0', 14],
  [22, 3.5, 11, '#f9c6d6', 11],
  [38, 1.2, 10, '#c9a7f2', 12],
  [55, 5, 12, '#f6a5c0', 10],
  [70, 2.2, 9.5, '#f9c6d6', 13],
  [84, 6.5, 11, '#c9a7f2', 11],
  [94, 4, 10, '#f6a5c0', 12],
]
// Sparkles: [left %, top %, delay s, size px].
const SPARKLES: [number, number, number, number][] = [
  [16, 30, 0, 16],
  [80, 26, 1.1, 20],
  [72, 48, 2.3, 12],
  [24, 58, 1.7, 12],
]

/** One soft leaf of the side foliage. */
function Frond({ d }: { d: string }) {
  return <path d={d} fill="currentColor" />
}

/** Foliage in the bottom corners (Garden page, grow screen, dashboard). */
export function CornerLeaves({ className = '' }: { className?: string }) {
  return (
    <>
      <svg className={`corner-leaves corner-leaves--left ${className}`} viewBox="0 0 100 120" aria-hidden>
        <Frond d="M30 120C10 90 8 50 22 10c10 40 18 75 8 110Z" />
        <Frond d="M38 120C40 85 55 55 85 35 75 70 60 100 38 120Z" />
        <Frond d="M24 120C14 100 0 92-10 90c8 14 20 26 34 30Z" />
      </svg>
      <svg className={`corner-leaves corner-leaves--right ${className}`} viewBox="0 0 100 120" aria-hidden>
        <Frond d="M70 120C90 90 92 50 78 10c-10 40-18 75-8 110Z" />
        <Frond d="M62 120C60 85 45 55 15 35c10 35 25 65 47 85Z" />
      </svg>
    </>
  )
}

/** Sun rays, drifting petals, twinkling sparkles and corner leaves behind the plant. */
export function GardenBackdrop() {
  return (
    <div className="garden-backdrop" aria-hidden>
      <span className="garden-backdrop__rays" />
      {PETALS.map(([left, delay, duration, color, size], i) => (
        <span
          key={`p${i}`}
          className="garden-backdrop__petal"
          style={{
            left: `${left}%`,
            animationDelay: `${delay}s`,
            animationDuration: `${duration}s`,
            background: color,
            width: size,
            height: size * 0.62,
          }}
        />
      ))}
      {SPARKLES.map(([left, top, delay, size], i) => (
        <svg
          key={`s${i}`}
          className="garden-backdrop__sparkle"
          viewBox="0 0 24 24"
          style={{ left: `${left}%`, top: `${top}%`, width: size, height: size, animationDelay: `${delay}s` }}
        >
          <path d="M12 0c1 7 5 11 12 12-7 1-11 5-12 12-1-7-5-11-12-12 7-1 11-5 12-12Z" fill="currentColor" />
        </svg>
      ))}
      <CornerLeaves />
    </div>
  )
}

/** "🌿 Fully Grown | ⭐ 775 XP" */
export function GardenPill({ level, xp }: { level: number; xp: number }) {
  return (
    <div className="garden-pill">
      <span className="garden-pill__part">
        <Icon name="leaf" size={20} />
        {stageName(level)}
      </span>
      <span className="garden-pill__divider" />
      <span className="garden-pill__part">
        <span className="garden-pill__star" aria-hidden>
          ⭐
        </span>
        {xp} XP
      </span>
    </div>
  )
}

/** A bar towards the next stage, with "2 more workouts to Budding". */
export function StageProgress({ xp, instant = false }: { xp: number; instant?: boolean }) {
  const { percent, workoutsLeft, next } = stageProgress(xp)
  return (
    <div className={`stage-progress${instant ? ' stage-progress--instant' : ''}`}>
      <div
        className="stage-progress__bar"
        role="progressbar"
        aria-label={next ? `Progress towards ${next}` : 'Fully grown'}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
      >
        <span className="stage-progress__fill" style={{ width: `${percent}%` }} />
      </div>
      <p className="stage-progress__text">
        {next
          ? `${workoutsLeft} more workout${workoutsLeft === 1 ? '' : 's'} to ${next}`
          : 'Fully grown! Keep going to keep your garden happy.'}
      </p>
    </div>
  )
}
