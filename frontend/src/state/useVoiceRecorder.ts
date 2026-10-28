import { useCallback, useEffect, useRef, useState } from 'react'

// Stop on its own at this length, well under the 4 MB the server accepts.
const MAX_RECORDING_SECONDS = 180

// MediaRecorder's formats differ by browser: webm/ogg on Chrome and Firefox,
// mp4 on Safari. First one this browser can record wins.
const MIME_TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus']

export type RecorderPhase = 'idle' | 'recording' | 'recorded'

// Records one voice note with MediaRecorder: start() asks for the microphone
// and records, stop() ends it and hands the finished recording to
// `onRecorded`; reset() discards it. The microphone is released as soon as
// recording stops, on auto-stop at MAX_RECORDING_SECONDS, and on unmount.
export function useVoiceRecorder(onRecorded: (recording: Blob) => void) {
  const [phase, setPhase] = useState<RecorderPhase>('idle')
  const [seconds, setSeconds] = useState(0)
  const [playbackUrl, setPlaybackUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const recorder = useRef<MediaRecorder | null>(null)
  const stream = useRef<MediaStream | null>(null)
  const timer = useRef<number | null>(null)
  const onRecordedRef = useRef(onRecorded)
  onRecordedRef.current = onRecorded

  const supported = typeof MediaRecorder !== 'undefined' && !!navigator.mediaDevices?.getUserMedia

  const releaseMic = useCallback(() => {
    if (timer.current !== null) window.clearInterval(timer.current)
    timer.current = null
    stream.current?.getTracks().forEach((track) => track.stop())
    stream.current = null
  }, [])

  // Let go of the microphone if the user leaves mid-recording.
  useEffect(() => releaseMic, [releaseMic])
  useEffect(
    () => () => {
      if (playbackUrl) URL.revokeObjectURL(playbackUrl)
    },
    [playbackUrl],
  )

  const stop = useCallback(() => {
    if (recorder.current?.state === 'recording') recorder.current.stop()
  }, [])

  const start = useCallback(async () => {
    setError(null)
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      setError('We could not use your microphone. Allow microphone access in your browser settings and try again.')
      return
    }
    const mimeType = MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type))
    const rec = new MediaRecorder(stream.current, mimeType ? { mimeType } : undefined)
    const chunks: Blob[] = []
    rec.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.push(e.data)
    }
    rec.onstop = () => {
      releaseMic()
      const blob = new Blob(chunks, { type: rec.mimeType || mimeType || 'audio/webm' })
      setPlaybackUrl(URL.createObjectURL(blob))
      setPhase('recorded')
      onRecordedRef.current(blob)
    }
    recorder.current = rec
    rec.start()
    setSeconds(0)
    setPhase('recording')
    timer.current = window.setInterval(() => setSeconds((s) => s + 1), 1000)
  }, [releaseMic])

  // Auto-stop at the length limit.
  useEffect(() => {
    if (phase === 'recording' && seconds >= MAX_RECORDING_SECONDS) stop()
  }, [phase, seconds, stop])

  const reset = useCallback(() => {
    setPlaybackUrl(null)
    setPhase('idle')
  }, [])

  return { phase, seconds, playbackUrl, error, supported, start, stop, reset }
}
