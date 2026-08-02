interface Props {
  index: number
  reps: string | null
  checked: boolean
  disabled?: boolean
  onToggle: (checked: boolean) => void
}

export function SetRow({ index, reps, checked, disabled, onToggle }: Props) {
  return (
    <label className="set-row">
      <span>
        Set {index + 1}: {reps ?? '—'} Reps
      </span>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onToggle(e.target.checked)}
      />
    </label>
  )
}
