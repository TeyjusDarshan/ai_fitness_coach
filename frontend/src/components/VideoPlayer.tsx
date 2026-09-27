interface Props {
  videoUrl: string | null
}

// Accepts the handful of URL shapes YouTube actually hands out
// (watch?v=, youtu.be/, shorts/, or an already-embed URL) and returns the
// //www.youtube.com/embed/<id> form an <iframe> can load, or null if
// `url` isn't a YouTube link we recognize.
function youtubeEmbedUrl(url: string): string | null {
  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    return null
  }

  const host = parsed.hostname.replace(/^www\./, '')

  if (host === 'youtu.be') {
    const id = parsed.pathname.slice(1)
    return id ? `https://www.youtube.com/embed/${id}` : null
  }

  if (host === 'youtube.com' || host === 'm.youtube.com') {
    if (parsed.pathname === '/watch') {
      const id = parsed.searchParams.get('v')
      return id ? `https://www.youtube.com/embed/${id}` : null
    }
    if (parsed.pathname.startsWith('/embed/')) {
      return url
    }
    const shortsMatch = parsed.pathname.match(/^\/shorts\/([^/]+)/)
    if (shortsMatch) {
      return `https://www.youtube.com/embed/${shortsMatch[1]}`
    }
  }

  return null
}

export function VideoPlayer({ videoUrl }: Props) {
  const embedUrl = videoUrl ? youtubeEmbedUrl(videoUrl) : null

  if (!embedUrl) {
    return (
      <div className="video-placeholder">
        <img src="/exercise-placeholder.jpg" alt="Exercise demonstration placeholder" />
        <div className="video-placeholder__controls">
          <span aria-hidden>▶</span>
          <div className="video-placeholder__bar" />
          <span aria-hidden>🔊</span>
          <span aria-hidden>⤢</span>
        </div>
      </div>
    )
  }

  return (
    <div className="video-placeholder">
      <iframe
        className="video-placeholder__iframe"
        src={embedUrl}
        title="Exercise demonstration"
        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
        allowFullScreen
      />
    </div>
  )
}
