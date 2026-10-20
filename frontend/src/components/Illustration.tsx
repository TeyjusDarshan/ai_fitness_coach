// Decorative scene from the mockup's style: a warm sun, soft leaves, and a
// figure holding a lunge stretch, all in the app's greens. Purely visual.
interface Props {
  className?: string
}

export function Illustration({ className }: Props) {
  return (
    <svg viewBox="0 0 160 140" className={className} aria-hidden>
      <circle cx="112" cy="30" r="20" fill="#f6d47a" opacity="0.85" />
      <path d="M128 132c-4-26 4-50 22-66-4 24-10 46-22 66Z" fill="#9cc49f" />
      <path d="M138 132c2-20 10-36 22-44-6 18-12 32-22 44Z" fill="#6fa77a" />
      <path d="M22 132c-2-22-12-38-22-46 4 20 10 34 22 46Z" fill="#b9d6b6" />
      <ellipse cx="80" cy="133" rx="58" ry="5" fill="#e2dac8" />
      {/* figure: head, torso, front leg bent, back leg extended, arm forward */}
      <circle cx="76" cy="40" r="9" fill="#2a5b44" />
      <path d="M76 50 70 86" stroke="#5f9b78" strokeWidth="13" strokeLinecap="round" />
      <path d="M72 58 98 68" stroke="#5f9b78" strokeWidth="7" strokeLinecap="round" />
      <path d="M70 86 96 98 98 128" stroke="#1f5c45" strokeWidth="9" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      <path d="M70 86 44 108 22 128" stroke="#1f5c45" strokeWidth="9" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      <path d="M98 128h10M22 128h-6" stroke="#17402f" strokeWidth="6" strokeLinecap="round" />
    </svg>
  )
}
