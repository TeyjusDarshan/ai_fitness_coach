import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAppState } from '../state/AppStateContext'
import { Icon, type IconName } from './Icon'

// The app's two homes, for clients with diet tracking on: Workouts (the
// dashboard, where the app opens) and Diet (Your Food).
const TABS: { path: string; label: string; icon: IconName }[] = [
  { path: '/', label: 'Workouts', icon: 'dumbbell' },
  { path: '/food', label: 'Diet', icon: 'bowl' },
]

// A bar fixed to the bottom of the two home screens, shown only to clients
// the coach switched diet tracking on for. While it's shown, body gets
// `with-bottom-nav` so those screens leave room for it.
export function BottomNav() {
  const { authStatus, dietEnabled } = useAppState()
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const shown = authStatus === 'signedIn' && dietEnabled && TABS.some((tab) => tab.path === pathname)

  useEffect(() => {
    document.body.classList.toggle('with-bottom-nav', shown)
    return () => document.body.classList.remove('with-bottom-nav')
  }, [shown])

  if (!shown) return null
  return (
    <nav className="bottom-nav" aria-label="Sections">
      {TABS.map((tab) => {
        const active = pathname === tab.path
        return (
          <button
            key={tab.path}
            className={`bottom-nav__tab${active ? ' bottom-nav__tab--active' : ''}`}
            aria-current={active ? 'page' : undefined}
            onClick={() => !active && navigate(tab.path)}
          >
            <Icon name={tab.icon} size={22} />
            {tab.label}
          </button>
        )
      })}
    </nav>
  )
}
