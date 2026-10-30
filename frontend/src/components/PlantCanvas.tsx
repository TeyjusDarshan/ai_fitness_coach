import { useEffect, useRef } from 'react'
import { PlantScene } from '../plant3d/PlantScene'

// The step the plant was last shown at, per user, so coming back after a
// workout grows it from there with sparkles instead of jumping.
const storageKey = (userId: string) => `plant-step:${userId}`

function readShownStep(userId: string): number | null {
  try {
    const value = localStorage.getItem(storageKey(userId))
    return value === null ? null : Number(value)
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
}

/** The 3D plant. Loaded lazily (it carries three.js); renders nothing without WebGL. */
export default function PlantCanvas({ step, userId }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const sceneRef = useRef<PlantScene | null>(null)
  // The step it showed last visit, read once (refs survive StrictMode's
  // effect re-runs, so the grow-up animation still plays there).
  const startStepRef = useRef(readShownStep(userId))
  const stepRef = useRef(step)
  stepRef.current = step

  useEffect(() => {
    let scene: PlantScene
    try {
      scene = new PlantScene(containerRef.current!)
    } catch {
      return // no WebGL: the backdrop and level card still show
    }
    sceneRef.current = scene
    const start = startStepRef.current
    scene.setStep(start !== null && start < stepRef.current ? start : stepRef.current, false)
    scene.setStep(stepRef.current, true)
    return () => {
      scene.dispose()
      sceneRef.current = null
    }
  }, [])

  // A level gained while the dashboard is open grows in place.
  useEffect(() => {
    sceneRef.current?.setStep(step, true)
    saveShownStep(userId, step)
  }, [step, userId])

  return <div ref={containerRef} className="plant-hero__canvas" aria-hidden />
}
