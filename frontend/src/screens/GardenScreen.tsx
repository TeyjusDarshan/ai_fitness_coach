import { Suspense, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { GardenBackdrop, GardenPill, LazyPlantCanvas, StageProgress } from '../components/Garden'
import { Icon } from '../components/Icon'
import { levelForPoints } from '../plant3d/levels'
import { useAppState } from '../state/AppStateContext'

/** "Your Garden": her plant full screen, its stage and XP, and how far the next stage is. */
export function GardenScreen() {
  const { userId, dashboard, refreshDashboard } = useAppState()
  const navigate = useNavigate()

  useEffect(() => {
    if (!dashboard) refreshDashboard().catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const xp = dashboard?.points ?? 0
  const { level } = levelForPoints(xp)

  return (
    <div className="garden-screen">
      <GardenBackdrop />
      <header className="garden-screen__head">
        <button className="page-header__back" onClick={() => navigate('/')} aria-label="Back">
          <Icon name="chevronLeft" size={22} />
        </button>
        <h1 className="garden-screen__title">Your Garden</h1>
      </header>
      {dashboard && (
        <>
          <GardenPill level={level} xp={xp} />
          <div className="garden-screen__stage">
            <Suspense fallback={null}>
              <LazyPlantCanvas step={level} userId={userId ?? ''} />
            </Suspense>
          </div>
          <div className="garden-screen__foot">
            <StageProgress xp={xp} />
            <p className="garden-screen__hint">Tap or swipe the plant to make it sway.</p>
          </div>
        </>
      )}
    </div>
  )
}
