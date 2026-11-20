import { useEffect, useId, useLayoutEffect, useRef, type KeyboardEvent } from 'react'

const ROW_PX = 44
const VISIBLE_ROWS = 5
const SETTLE_MS = 120

interface Props {
  values: number[]
  value: number
  onChange: (value: number) => void
  unit?: string
  label: string
}

// A scroll wheel: the list snaps row by row and the row in the centre band
// is the value. Tap a row or use the arrow keys to move to it.
export function WheelPicker({ values, value, onChange, unit, label }: Props) {
  const listRef = useRef<HTMLDivElement>(null)
  const idPrefix = useId()
  const settleTimer = useRef<number | undefined>(undefined)
  const index = Math.max(0, values.indexOf(value))

  useLayoutEffect(() => {
    // Start on the current value (only on mount: later changes come from
    // scrolling, which already put the list there).
    if (listRef.current) listRef.current.scrollTop = index * ROW_PX
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => () => window.clearTimeout(settleTimer.current), [])

  const scrollToIndex = (next: number) => {
    const clamped = Math.max(0, Math.min(values.length - 1, next))
    listRef.current?.scrollTo({ top: clamped * ROW_PX, behavior: 'smooth' })
    onChange(values[clamped])
  }

  const onScroll = () => {
    // Read the value once the scroll settles (scrollend isn't everywhere).
    window.clearTimeout(settleTimer.current)
    settleTimer.current = window.setTimeout(() => {
      const list = listRef.current
      if (!list) return
      const settled = values[Math.max(0, Math.min(values.length - 1, Math.round(list.scrollTop / ROW_PX)))]
      if (settled !== value) onChange(settled)
    }, SETTLE_MS)
  }

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
      event.preventDefault()
      scrollToIndex(index + (event.key === 'ArrowDown' ? 1 : -1))
    }
  }

  return (
    <div className="wheel" style={{ height: ROW_PX * VISIBLE_ROWS }}>
      <div className="wheel__band" style={{ height: ROW_PX }} aria-hidden="true">
        {unit && <span className="wheel__unit">{unit}</span>}
      </div>
      <div
        ref={listRef}
        className="wheel__list"
        role="listbox"
        aria-label={label}
        aria-activedescendant={`${idPrefix}-${value}`}
        tabIndex={0}
        onScroll={onScroll}
        onKeyDown={onKeyDown}
        style={{ paddingBlock: ROW_PX * Math.floor(VISIBLE_ROWS / 2) }}
      >
        {values.map((option, i) => (
          <div
            key={option}
            id={`${idPrefix}-${option}`}
            role="option"
            aria-selected={option === value}
            className={`wheel__row${option === value ? ' wheel__row--on' : ''}`}
            style={{ height: ROW_PX }}
            onClick={() => scrollToIndex(i)}
          >
            {option}
          </div>
        ))}
      </div>
    </div>
  )
}
