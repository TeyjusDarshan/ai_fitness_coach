import { Suspense, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { LevelCard } from '../components/LevelCard'
import { LazyPlantCanvas, PlantBackdrop } from '../components/PlantHero'
import { levelForPoints } from '../plant3d/levels'
import { useAppState } from '../state/AppStateContext'
import { useCompleteSession } from '../state/useCompleteSession'

// Timeline (ms from the result arriving): the +25 pops in, then the points
// count up while the bar fills, and on a level-up the plant grows.
const POP_AT = 500
const COUNT_AT = 900
const COUNT_MS = 900
// PlantScene grows a step in ~1.4 s (faster when several are owed).
const GROW_MS_PER_LEVEL = 1400
const CONTINUE_AFTER_MS = 500
// Start anyway if the plant is slow to appear (slow phone or network).
const PLANT_WAIT_MS = 4000

/**
 * Between the finished workout and its summary: completes the workout, then
 * shows the plant full screen earning the workout's grow points — growing a
 * stage if they unlock a new level — and a button on to the summary, which
 * gets this screen's result instead of completing again.
 */
export function GrowScreen() {
  const { userId } = useAppState()
  const navigate = useNavigate()
  const { dayNumber } = useParams()
  const dayNum = Number(dayNumber)
  const { summary, error } = useCompleteSession(dayNum)

  const [popped, setPopped] = useState(false)
  const [shownPoints, setShownPoints] = useState<number | null>(null)
  const [grown, setGrown] = useState(false)
  const [puffKey, setPuffKey] = useState(0)
  const [canContinue, setCanContinue] = useState(false)
  // The celebration starts once the plant is on screen, so it isn't missed.
  const [plantReady, setPlantReady] = useState(false)

  const earned = summary?.points_earned ?? 0
  const before = summary ? summary.points - earned : 0
  const levelBefore = levelForPoints(before).level
  const levelAfter = summary ? levelForPoints(summary.points).level : 0
  const levelsGained = levelAfter - levelBefore

  function goToSummary(replace = false) {
    navigate(`/day/${dayNum}/summary`, { replace, state: summary ? { summary } : undefined })
  }

  useEffect(() => {
    if (!summary) return
    // Already completed before (nothing new earned): straight to the summary.
    if (summary.points_earned === 0) {
      goToSummary(true)
      return
    }
    setShownPoints(before)
    const wait = window.setTimeout(() => setPlantReady(true), PLANT_WAIT_MS)
    return () => window.clearTimeout(wait)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [summary])

  useEffect(() => {
    if (!summary || !plantReady || summary.points_earned === 0) return
    let frame = 0
    const timers = [
      window.setTimeout(() => setPopped(true), POP_AT),
      window.setTimeout(() => {
        const start = performance.now()
        const tick = (now: number) => {
          const t = Math.min(1, (now - start) / COUNT_MS)
          setShownPoints(Math.round(before + earned * t))
          if (t < 1) frame = requestAnimationFrame(tick)
        }
        frame = requestAnimationFrame(tick)
        if (levelsGained > 0) setGrown(true)
        else setPuffKey((k) => k + 1)
      }, COUNT_AT),
      window.setTimeout(
        () => setCanContinue(true),
        COUNT_AT + Math.max(COUNT_MS, levelsGained * GROW_MS_PER_LEVEL) + CONTINUE_AFTER_MS,
      ),
    ]
    return () => {
      timers.forEach((t) => window.clearTimeout(t))
      cancelAnimationFrame(frame)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [summary, plantReady])

  if (error) {
    return (
      <div className="screen">
        <div className="error-banner">{error}</div>
        <button className="btn-secondary" onClick={() => navigate('/', { replace: true })}>
          Back to Dashboard
        </button>
      </div>
    )
  }

  if (!summary || shownPoints === null) {
    return (
      <div className="screen">
        <div className="spinner" />
      </div>
    )
  }

  const levelUp = grown && levelsGained > 0

  return (
    <div className="grow-screen">
      <PlantBackdrop />
      <header className="grow-screen__head">
        <h1 className="grow-screen__title">{levelUp ? 'Level up!' : 'Workout complete!'}</h1>
        <p className={`grow-screen__subtitle${levelUp ? ' grow-screen__subtitle--level' : ''}`}>
          {levelUp ? `Your plant reached Level ${levelAfter}` : 'Your plant is growing'}
        </p>
      </header>

      <div className="grow-screen__stage">
        <Suspense fallback={null}>
          <LazyPlantCanvas
            step={grown ? levelAfter : levelBefore}
            fromStep={levelBefore}
            userId={userId ?? ''}
            puffKey={puffKey}
            onReady={() => setPlantReady(true)}
          />
        </Suspense>
        {popped && (
          <span className="grow-screen__points" aria-live="polite">
            +{earned} points
          </span>
        )}
      </div>

      <div className="grow-screen__foot">
        <LevelCard points={shownPoints} plantLevel={levelForPoints(shownPoints)} instant />
        <button
          className={`btn-primary grow-screen__continue${canContinue ? ' grow-screen__continue--shown' : ''}`}
          disabled={!canContinue}
          onClick={() => goToSummary()}
        >
          Continue
        </button>
      </div>
    </div>
  )
}
