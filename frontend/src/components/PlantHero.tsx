import { lazy, Suspense } from 'react'

// The 3D plant carries three.js, so it loads on its own after the page.
export const LazyPlantCanvas = lazy(() => import('./PlantCanvas'))

/** One soft leaf of the backdrop's side foliage. */
function Frond({ d }: { d: string }) {
  return <path d={d} fill="currentColor" />
}

/** The sun and side foliage drawn behind the plant (dashboard and grow screen). */
export function PlantBackdrop() {
  return (
    <>
      <span className="plant-hero__sun" aria-hidden />
      <svg className="plant-hero__foliage plant-hero__foliage--left" viewBox="0 0 100 120" aria-hidden>
        <Frond d="M30 120C10 90 8 50 22 10c10 40 18 75 8 110Z" />
        <Frond d="M38 120C40 85 55 55 85 35 75 70 60 100 38 120Z" />
        <Frond d="M24 120C14 100 0 92-10 90c8 14 20 26 34 30Z" />
      </svg>
      <svg className="plant-hero__foliage plant-hero__foliage--right" viewBox="0 0 100 120" aria-hidden>
        <Frond d="M70 120C90 90 92 50 78 10c-10 40-18 75-8 110Z" />
        <Frond d="M62 120C60 85 45 55 15 35c10 35 25 65 47 85Z" />
      </svg>
    </>
  )
}

interface Props {
  name: string
  userId: string
  step: number
}

/** The dashboard's fixed top: greeting, sunlit backdrop and the growing plant. */
export function PlantHero({ name, userId, step }: Props) {
  return (
    <div className="plant-hero">
      <PlantBackdrop />
      <h1 className="plant-hero__greeting">Hi {name},</h1>
      <Suspense fallback={null}>
        <LazyPlantCanvas step={step} userId={userId} />
      </Suspense>
    </div>
  )
}
