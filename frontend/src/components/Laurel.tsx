// A sprig of leaves either side of the trophy.
export function Laurel({ side }: { side: 'left' | 'right' }) {
  return (
    <svg viewBox="0 0 30 60" className={`laurel laurel--${side}`} aria-hidden>
      <path d="M22 58C10 46 6 30 12 6" stroke="#5f9b78" strokeWidth="2.5" fill="none" strokeLinecap="round" />
      {[12, 24, 36, 48].map((y) => (
        <g key={y}>
          <ellipse cx={y < 30 ? 6 : 9} cy={y} rx="6" ry="3" transform={`rotate(-35 ${y < 30 ? 6 : 9} ${y})`} fill="#7fb38c" />
          <ellipse cx={y < 30 ? 17 : 21} cy={y - 4} rx="6" ry="3" transform={`rotate(35 ${y < 30 ? 17 : 21} ${y - 4})`} fill="#9cc49f" />
        </g>
      ))}
    </svg>
  )
}
