import { useEffect, useRef } from 'react'
import { PlantScene } from '../plant3d/PlantScene'
import { MAX_LEVEL } from '../plant3d/levels'

// The step the plant was last shown at, per user, so coming back after a
// workout grows it from there with sparkles instead of jumping.
const storageKey = (userId: string) => `plant-step:${userId}`

function readShownStep(userId: string): number | null {
  try {
    const value = localStorage.getItem(storageKey(userId))
    if (value === null) return null
    // Only a real step counts: anything else (edited by hand, say) would
    // otherwise animate from wherever it says, e.g. through millions of steps.
    const step = Number(value)
    return Number.isInteger(step) && step >= 0 && step <= MAX_LEVEL ? step : null
  } catch {
    return null
  }
}

function saveShownStep(userId: string, step: number) {
  try {
    localStorage.setItem(storageKey(userId), String(step))
  } catch {
    // best-effort: the plant just won't animate up next time
  }
}

interface Props {
  step: number
  userId: string
  // Stage to grow from on mount, instead of the one saved on the device.
  fromStep?: number
  // Changing this sends a gust through the plant.
  puffKey?: number
  // Called once the plant is on screen (or straight away without WebGL).
  onReady?: () => void
}

/** The 3D plant. Loaded lazily (it carries three.js); renders nothing without WebGL. */
export default function PlantCanvas({ step, userId, fromStep, puffKey = 0, onReady }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const sceneRef = useRef<PlantScene | null>(null)
  // The step it showed last visit, read once (refs survive StrictMode's
  // effect re-runs, so the grow-up animation still plays there).
  const startStepRef = useRef(fromStep ?? readShownStep(userId))
  const stepRef = useRef(step)
  stepRef.current = step

  useEffect(() => {
    let scene: PlantScene
    try {
      scene = new PlantScene(containerRef.current!)
    } catch {
      onReady?.()
      return // no WebGL: the backdrop and level card still show
    }
    sceneRef.current = scene
    const start = startStepRef.current
    scene.setStep(start !== null && start < stepRef.current ? start : stepRef.current, false)
    scene.setStep(stepRef.current, true)
    // Two frames: the first draws (and compiles the shaders), the second is after it's shown.
    let frame = requestAnimationFrame(() => {
      frame = requestAnimationFrame(() => onReady?.())
    })
    return () => {
      cancelAnimationFrame(frame)
      scene.dispose()
      sceneRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // A level gained while the dashboard is open grows in place.
  useEffect(() => {
    sceneRef.current?.setStep(step, true)
    saveShownStep(userId, step)
  }, [step, userId])

  useEffect(() => {
    if (puffKey) sceneRef.current?.puff()
  }, [puffKey])

  return <div ref={containerRef} className="plant-hero__canvas" aria-hidden />
}
