import { useState, type ReactNode } from 'react'
import { Icon, type IconName } from './Icon'

// A dashboard group (Upcoming / Past Workouts): a tappable header with an
// icon, title and one-line summary that opens to show its workouts.
// Collapsed by default.
export function CollapsibleSection({
  title,
  summary,
  icon,
  variant,
  children,
}: {
  title: string
  summary: string
  icon: IconName
  variant: 'upcoming' | 'past'
  children: ReactNode
}) {
  const [open, setOpen] = useState(false)

  return (
    <section className={`collapsible collapsible--${variant}`}>
      <button className="collapsible__head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="collapsible__icon">
          <Icon name={icon} size={24} />
        </span>
        <span className="collapsible__text">
          <span className="collapsible__title">{title}</span>
          <span className="collapsible__summary">{summary}</span>
        </span>
        <span className={`collapsible__chevron${open ? ' collapsible__chevron--open' : ''}`} aria-hidden>
          <Icon name="chevronRight" size={20} />
        </span>
      </button>
      {open && <div className="collapsible__body">{children}</div>}
    </section>
  )
}
