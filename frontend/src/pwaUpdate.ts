import { registerSW } from 'virtual:pwa-register'

// How often an open app asks the server whether a new version was deployed.
// Browsers otherwise only check on navigation (and about daily), so a PWA
// left open or resumed from the background would keep running old code.
const UPDATE_CHECK_MS = 30 * 60 * 1000

// Keeps the installed app current without the user refreshing: checks for a
// new service worker on an interval and whenever the app returns to the
// foreground, then applies it (activating the new worker and reloading the
// page) at a moment that won't interrupt anything — straight away on the
// dashboard, otherwise as soon as the app is backgrounded, so the user comes
// back to the new version. Everything mid-workout is saved server-side, but
// a reload would still lose the rest timer.
export function keepAppUpdated() {
  let registration: ServiceWorkerRegistration | undefined
  let updateReady = false

  const checkForUpdate = () => {
    void registration?.update().catch(() => {
      // offline — try again next time
    })
  }

  const applyIfSafe = () => {
    if (!updateReady) return
    if (document.visibilityState === 'hidden' || window.location.pathname === '/') {
      void applyUpdate(true)
    }
  }

  const applyUpdate = registerSW({
    onNeedRefresh() {
      updateReady = true
      applyIfSafe()
    },
    onRegisteredSW(_url, reg) {
      registration = reg
      setInterval(checkForUpdate, UPDATE_CHECK_MS)
    },
  })

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') checkForUpdate()
    applyIfSafe()
  })
}
