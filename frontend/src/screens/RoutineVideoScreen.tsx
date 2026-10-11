import { useState } from 'react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { useAppState } from '../state/AppStateContext'
import { firstIncompleteIndex } from '../utils'
import { COOLDOWN_VIDEO_ID, WARMUP_VIDEO_ID } from '../constants'

const ROUTINES = {
  warmup: {
    videoId: WARMUP_VIDEO_ID,
    title: 'Warm-up',
    startLabel: 'Start warm-up',
    doneLabel: 'Start workout',
  },
  cooldown: {
    videoId: COOLDOWN_VIDEO_ID,
    title: 'Cool-down',
    startLabel: 'Start cool-down',
    doneLabel: 'Finish workout',
  },
} as const

function embedUrl(videoId: string): string {
  const params = new URLSearchParams({ autoplay: '1', playsinline: '1', rel: '0', modestbranding: '1' })
  return `https://www.youtube.com/embed/${videoId}?${params}`
}

// The warm-up shown between "Start" and the first exercise, and the
// cool-down shown between the last exercise and the summary. Always laid out
// in landscape (rotated 90° while the phone is held upright — see
// .routine-screen__stage): a 16:9 video frame on a dark textured page, with
// the title and the button that moves on in a side column, available the
// whole time. The frame first shows a start button and loads the video when
// it's tapped.
export function RoutineVideoScreen({ kind }: { kind: 'warmup' | 'cooldown' }) {
  const { dashboard } = useAppState()
  const navigate = useNavigate()
  const { dayNumber } = useParams()
  const [playing, setPlaying] = useState(false)
  const dayNum = Number(dayNumber)
  const day = dashboard?.days.find((d) => d.day_number === dayNum)
  const routine = ROUTINES[kind]

  if (!day || day.is_rest_day || day.locked) return <Navigate to="/" replace />

  function handleDone() {
    const next =
      kind === 'warmup' ? `/day/${dayNum}/exercise/${firstIncompleteIndex(day!)}` : `/day/${dayNum}/summary`
    navigate(next, { replace: true })
  }

  return (
    <div className="routine-screen">
      <div className="routine-screen__stage">
        <div className="routine-screen__frame">
          {playing ? (
            <iframe
              src={embedUrl(routine.videoId)}
              title={routine.title}
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
              allowFullScreen
            />
          ) : (
            <button className="routine-screen__start" onClick={() => setPlaying(true)}>
              <span className="routine-screen__play" aria-hidden>
                ▶
              </span>
              {routine.startLabel}
            </button>
          )}
        </div>
        <div className="routine-screen__side">
          <h1 className="routine-screen__title">{routine.title}</h1>
          <button className="btn-primary routine-screen__done" onClick={handleDone}>
            {routine.doneLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
