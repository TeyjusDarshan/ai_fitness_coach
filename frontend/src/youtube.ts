// YouTube link helpers shared by the exercise video player and the workout
// detail screen's thumbnails.

// The video id from the handful of URL shapes YouTube actually hands out
// (watch?v=, youtu.be/, shorts/, or an already-embed URL), or null if `url`
// isn't a YouTube link we recognize.
function youtubeVideoId(url: string): string | null {
  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    return null
  }

  const host = parsed.hostname.replace(/^www\./, '')

  if (host === 'youtu.be') {
    return parsed.pathname.slice(1) || null
  }

  if (host === 'youtube.com' || host === 'm.youtube.com') {
    if (parsed.pathname === '/watch') {
      return parsed.searchParams.get('v')
    }
    const match = parsed.pathname.match(/^\/(?:embed|shorts)\/([^/]+)/)
    if (match) return match[1]
  }

  return null
}

// The //www.youtube.com/embed/<id> form an <iframe> can load.
export function youtubeEmbedUrl(url: string): string | null {
  const id = youtubeVideoId(url)
  return id ? `https://www.youtube.com/embed/${id}` : null
}

export function youtubeThumbnailUrl(url: string | null): string | null {
  const id = url ? youtubeVideoId(url) : null
  return id ? `https://img.youtube.com/vi/${id}/mqdefault.jpg` : null
}
