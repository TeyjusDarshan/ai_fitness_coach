export function VideoPlaceholder() {
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
