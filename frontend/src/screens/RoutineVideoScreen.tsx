import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { FullscreenVideo } from '../components/FullscreenVideo'
import { useAppState } from '../state/AppStateContext'
import { firstIncompleteIndex } from '../utils'
import { COOLDOWN_VIDEO_ID, WARMUP_VIDEO_ID } from '../constants'

// The warm-up played between "Start" and the first exercise, and the
// cool-down played between the last exercise and the summary.
export function RoutineVideoScreen({ kind }: { kind: 'warmup' | 'cooldown' }) {
  const { dashboard } = useAppState()
  const navigate = useNavigate()
  const { dayNumber } = useParams()
  const dayNum = Number(dayNumber)
  const day = dashboard?.days.find((d) => d.day_number === dayNum)

  if (!day || day.is_rest_day || day.locked) return <Navigate to="/" replace />

  if (kind === 'warmup') {
    return (
      <FullscreenVideo
        videoId={WARMUP_VIDEO_ID}
        title="Warm-up"
        doneLabel="Start workout"
        onDone={() => navigate(`/day/${dayNum}/exercise/${firstIncompleteIndex(day)}`, { replace: true })}
      />
    )
  }

  return (
    <FullscreenVideo
      videoId={COOLDOWN_VIDEO_ID}
      title="Cool-down"
      doneLabel="Finish workout"
      onDone={() => navigate(`/day/${dayNum}/summary`, { replace: true })}
    />
  )
}
