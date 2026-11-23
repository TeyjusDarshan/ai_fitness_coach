// What the dashboard screens show besides API data, fetched while the app
// starts so they appear complete: the 3D plant's code (three.js, its own
// chunk) and the Today card's illustrations.
const ILLUSTRATIONS = ['/illustrations/strength.webp', '/illustrations/cardio.webp']

// Never hold the app back longer than this for them (slow network: they
// simply pop in once loaded).
const MAX_WAIT_MS = 2500

function loadImage(src: string): Promise<void> {
  return new Promise((resolve) => {
    const img = new Image()
    img.onload = img.onerror = () => resolve()
    img.src = src
  })
}

export function preloadHomeAssets(): Promise<void> {
  const all = Promise.all([
    import('./components/PlantCanvas').catch(() => undefined),
    ...ILLUSTRATIONS.map(loadImage),
  ]).then(() => undefined)
  return Promise.race([all, new Promise<void>((resolve) => setTimeout(resolve, MAX_WAIT_MS))])
}
