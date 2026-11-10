import type { EffortTone } from './effortLevels'

// The coloured face on each effort option: smiling, flat or strained.
export function FeedbackFace({ tone }: { tone: EffortTone }) {
  const mouth =
    tone === 'easy' ? 'M8 13.5c1 2 2.4 3 4 3s3-1 4-3' : tone === 'about' ? 'M8.5 15h7' : 'M8.5 16.5c1-1.4 2.2-2 3.5-2s2.5.6 3.5 2'
  return (
    <svg className="feedback-option__face" viewBox="0 0 24 24" width="44" height="44" aria-hidden>
      <circle cx="12" cy="12" r="12" fill="currentColor" />
      <circle cx="9" cy="9.5" r="1.3" fill="#fff" />
      <circle cx="15" cy="9.5" r="1.3" fill="#fff" />
      <path d={mouth} stroke="#fff" strokeWidth="1.7" fill="none" strokeLinecap="round" />
    </svg>
  )
}
