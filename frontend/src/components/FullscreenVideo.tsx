import { useEffect, useRef, useState } from 'react'

// Minimal slice of the YouTube IFrame Player API this component uses
// (https://developers.google.com/youtube/iframe_api_reference).
interface YTPlayer {
  destroy(): void
}

interface YTNamespace {
  Player: new (
    element: HTMLElement,
    options: {
      videoId: string
      playerVars?: Record<string, number | string>
      events?: {
        onStateChange?: (event: { data: number }) => void
        onError?: () => void
      }
    },
  ) => YTPlayer
  PlayerState: { ENDED: number }
}

declare global {
  interface Window {
    YT?: YTNamespace
    onYouTubeIframeAPIReady?: () => void
  }
}

let apiPromise: Promise<YTNamespace> | null = null

function loadYouTubeApi(): Promise<YTNamespace> {
  if (window.YT?.Player) return Promise.resolve(window.YT)
  if (!apiPromise) {
    apiPromise = new Promise((resolve, reject) => {
      const previous = window.onYouTubeIframeAPIReady
      window.onYouTubeIframeAPIReady = () => {
        previous?.()
        resolve(window.YT!)
      }
      const script = document.createElement('script')
      script.src = 'https://www.youtube.com/iframe_api'
      script.onerror = () => {
        apiPromise = null
        reject(new Error('Could not load the YouTube player.'))
      }
      document.head.appendChild(script)
    })
  }
  return apiPromise
}

// Real fullscreen + landscape lock where the browser allows it (Android
// Chrome, desktop). Both need a recent user gesture, which the tap that
// navigated here usually still counts as. iPhone Safari supports neither for
// a page, so the CSS in .fullscreen-video rotates the stage instead whenever
// the device is still held in portrait.
async function enterLandscapeFullscreen() {
  try {
    if (!document.fullscreenElement) await document.documentElement.requestFullscreen?.()
  } catch {
    return false
  }
  try {
    await (screen.orientation as ScreenOrientation & { lock?: (o: string) => Promise<void> }).lock?.('landscape')
  } catch {
    // Orientation lock unsupported; the CSS rotation covers it.
  }
  return true
}

function exitLandscapeFullscreen() {
  try {
    screen.orientation?.unlock?.()
  } catch {
    // not locked / unsupported
  }
  if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {})
}

interface Props {
  videoId: string
  title: string
  doneLabel: string
  onDone: () => void
}

// Plays one YouTube video over the whole screen in landscape, and shows the
// `doneLabel` button once it ends (or right away if it can't be played).
export function FullscreenVideo({ videoId, title, doneLabel, onDone }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [ended, setEnded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isFullscreen, setIsFullscreen] = useState(Boolean(document.fullscreenElement))

  useEffect(() => {
    let player: YTPlayer | null = null
    let cancelled = false

    loadYouTubeApi()
      .then((YT) => {
        if (cancelled || !containerRef.current) return
        // YT.Player replaces the element it's given with its <iframe>, so
        // hand it a node React doesn't manage.
        const mount = document.createElement('div')
        containerRef.current.appendChild(mount)
        player = new YT.Player(mount, {
          videoId,
          playerVars: { autoplay: 1, playsinline: 1, rel: 0, modestbranding: 1, fs: 0 },
          events: {
            onStateChange: (event) => {
              if (event.data === YT.PlayerState.ENDED) setEnded(true)
            },
            onError: () => {
              setError('This video can’t be played right now.')
              setEnded(true)
            },
          },
        })
      })
      .catch((e: Error) => {
        if (cancelled) return
        setError(e.message)
        setEnded(true)
      })

    const container = containerRef.current
    return () => {
      cancelled = true
      player?.destroy()
      container?.replaceChildren()
    }
  }, [videoId])

  useEffect(() => {
    const onChange = () => setIsFullscreen(Boolean(document.fullscreenElement))
    document.addEventListener('fullscreenchange', onChange)
    enterLandscapeFullscreen()
    return () => {
      document.removeEventListener('fullscreenchange', onChange)
      exitLandscapeFullscreen()
    }
  }, [])

  const canFullscreen = Boolean(document.documentElement.requestFullscreen)

  return (
    <div className="fullscreen-video" role="dialog" aria-label={title}>
      <div className="fullscreen-video__stage">
        <div className="fullscreen-video__player" ref={containerRef} />
        {canFullscreen && !isFullscreen && !ended && (
          <button className="fullscreen-video__expand" onClick={() => enterLandscapeFullscreen()}>
            ⤢ Full screen
          </button>
        )}
        {ended && (
          <div className="fullscreen-video__done">
            {error && <p className="fullscreen-video__error">{error}</p>}
            <button className="btn-primary fullscreen-video__done-btn" onClick={onDone}>
              {doneLabel}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
