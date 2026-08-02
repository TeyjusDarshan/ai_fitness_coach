import { useState } from 'react'

// UI-only stub: shows a recording indicator on tap, persists nothing.
// Real audio capture/upload is out of scope for this version.
export function VoiceNoteButton() {
  const [recording, setRecording] = useState(false)

  return (
    <button
      type="button"
      className="btn-secondary voice-note-btn"
      onClick={() => setRecording((r) => !r)}
    >
      <span className={recording ? 'voice-note-btn__dot voice-note-btn__dot--active' : 'voice-note-btn__dot'} aria-hidden>
        🎙
      </span>
      {recording ? 'Recording…' : 'Record Voice Note'}
    </button>
  )
}
