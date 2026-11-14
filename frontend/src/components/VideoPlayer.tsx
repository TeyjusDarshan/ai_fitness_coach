import { youtubeEmbedUrl } from '../youtube'
import { Icon } from './Icon'

interface Props {
  videoUrl: string | null
  // Start playing straight away (after a tap that asked for the video).
  autoplay?: boolean
}

export function VideoPlayer({ videoUrl, autoplay = false }: Props) {
  const baseUrl = videoUrl ? youtubeEmbedUrl(videoUrl) : null
  const embedUrl = baseUrl && autoplay ? `${baseUrl}?autoplay=1&playsinline=1&rel=0` : baseUrl

  if (!embedUrl) {
    return (
      <div className="video-placeholder">
        <img src="/exercise-placeholder.jpg" alt="Exercise demonstration placeholder" />
        <span className="video-placeholder__play">
          <Icon name="play" size={28} />
        </span>
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
