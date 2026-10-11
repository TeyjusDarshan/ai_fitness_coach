import { useMemo } from 'react'
import type { Category, LibraryExercise, PlanBuilderOptions, SlotTemplate } from '../../adminApi'
import {
  CATEGORIES,
  MAX_REPS,
  MAX_SETS,
  allSlots,
  dayDateIso,
  defaultReps,
  emptyDraft,
  isValidStartDate,
  isOutsideRepRange,
  isSlotComplete,
  matchesSlot,
  painfulJointsFor,
  todayIso,
  type PlanDraft,
  type SlotDraft,
} from './planDraft'
import { formatDayDate } from '../../utils'

// Step 2: pick a DAY_TEMPLATES plan type and fill every slot of every
// training day by hand.
export function PlannerStep({
  options,
  pain,
  planType,
  draft,
  coachNotes,
  startDate,
  onStartDateChange,
  onPlanTypeChange,
  onDraftChange,
  onCoachNotesChange,
  onBack,
  onReview,
}: {
  options: PlanBuilderOptions
  pain: Set<string>
  planType: string
  draft: PlanDraft
  coachNotes: string
  startDate: string
  onStartDateChange: (startDate: string) => void
  onPlanTypeChange: (planType: string, draft: PlanDraft) => void
  onDraftChange: (draft: PlanDraft) => void
  onCoachNotesChange: (notes: string) => void
  onBack: () => void
  onReview: () => void
}) {
  const template = options.templates[planType]
  const exercisesById = useMemo(() => new Map(options.exercises.map((ex) => [ex.id, ex])), [options.exercises])
  const slots = allSlots(draft)
  const readyCount = slots.filter(isSlotComplete).length
  const startDateValid = isValidStartDate(startDate)

  function changePlanType(next: string) {
    if (next === planType) return
    const hasPicks = slots.some((slot) => slot.exerciseId != null)
    if (hasPicks && !window.confirm('Switching plan type clears the exercises you picked. Continue?')) return
    onPlanTypeChange(next, emptyDraft(options.templates[next]))
  }

  function updateSlot(dayNumber: number, category: Category, index: number, patch: Partial<SlotDraft>) {
    const day = draft[dayNumber]
    const updated = day[category].map((slot, i) => (i === index ? { ...slot, ...patch } : slot))
    onDraftChange({ ...draft, [dayNumber]: { ...day, [category]: updated } })
  }

  function pickExercise(dayNumber: number, category: Category, index: number, value: string) {
    const exercise = value ? exercisesById.get(Number(value)) : undefined
    updateSlot(dayNumber, category, index, {
      exerciseId: exercise ? exercise.id : null,
      ...(exercise ? { reps: defaultReps(exercise) } : {}),
    })
  }

  return (
    <>
      <section className="card admin__section">
        <h2 className="admin__section-title">2 · Build the plan</h2>
        <div className="admin__field">
          <span>Plan type</span>
          <div className="admin__segmented" role="radiogroup">
            {Object.keys(options.templates).map((type) => (
              <button
                key={type}
                type="button"
                role="radio"
                aria-checked={type === planType}
                className={`admin__segment${type === planType ? ' admin__segment--active' : ''}`}
                onClick={() => changePlanType(type)}
              >
                {options.templates[type].label}
              </button>
            ))}
          </div>
        </div>
        <label className="admin__field">
          <span>Start date (day 1 — the client can’t start a day before its date)</span>
          <input
            className="login-screen__input"
            type="date"
            min={todayIso()}
            value={startDate}
            onChange={(e) => onStartDateChange(e.target.value)}
          />
          {!startDateValid && (
            <small className="admin__hint admin__hint--error">Pick today or a later date.</small>
          )}
        </label>
        <label className="admin__field">
          <span>Coach notes (optional, shown on the client’s dashboard)</span>
          <textarea
            className="login-screen__input admin__textarea"
            rows={3}
            value={coachNotes}
            onChange={(e) => onCoachNotesChange(e.target.value)}
          />
        </label>
      </section>

      {template.schedule.map((day) =>
        day.is_rest_day ? (
          <div key={day.day_number} className="admin__rest-day">
            {day.day_label}
            {startDateValid && ` · ${formatDayDate(dayDateIso(startDate, day.day_number))}`} · Rest
          </div>
        ) : (
          <section key={day.day_number} className="card admin__section">
            <h2 className="admin__section-title">
              {day.day_label}
              {startDateValid && ` · ${formatDayDate(dayDateIso(startDate, day.day_number))}`}
              <span className="admin__muted">· {day.split_name}</span>
            </h2>
            <div className="admin__slots">
              {CATEGORIES.map((category) =>
                day[category].map((slot, index) => {
                  const slotDraft = draft[day.day_number][category][index]
                  return (
                    <SlotEditor
                      key={`${category}-${index}`}
                      category={category}
                      slot={slot}
                      draft={slotDraft}
                      exercises={options.exercises}
                      exercise={slotDraft.exerciseId != null ? exercisesById.get(slotDraft.exerciseId) : undefined}
                      pain={pain}
                      onPick={(value) => pickExercise(day.day_number, category, index, value)}
                      onChange={(patch) => updateSlot(day.day_number, category, index, patch)}
                    />
                  )
                }),
              )}
            </div>
          </section>
        ),
      )}

      <div className="admin__footer">
        <p className="admin__hint">
          {readyCount} of {slots.length} slots ready
          {!startDateValid && ' · pick a start date'}
        </p>
        <div className="admin__actions">
          <button type="button" className="btn-secondary" onClick={onBack}>
            Back to profile
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={readyCount !== slots.length || !startDateValid}
            onClick={onReview}
          >
            Review plan
          </button>
        </div>
      </div>
    </>
  )
}

function SlotEditor({
  category,
  slot,
  draft,
  exercises,
  exercise,
  pain,
  onPick,
  onChange,
}: {
  category: Category
  slot: SlotTemplate
  draft: SlotDraft
  exercises: LibraryExercise[]
  exercise: LibraryExercise | undefined
  pain: Set<string>
  onPick: (value: string) => void
  onChange: (patch: Partial<SlotDraft>) => void
}) {
  const matching = exercises.filter((ex) => matchesSlot(ex, slot))
  const others = exercises.filter((ex) => !matchesSlot(ex, slot))
  const outsideRange = isOutsideRepRange(exercise, draft.reps)
  const painful = exercise ? painfulJointsFor(exercise, pain) : []

  const optionLabel = (ex: LibraryExercise, withType: boolean) =>
    `${painfulJointsFor(ex, pain).length ? '⚠ ' : ''}${ex.name}${withType ? ` (${ex.movement_type})` : ''}`

  return (
    <div className={`admin__slot${isSlotComplete(draft) ? ' admin__slot--ready' : ''}`}>
      <div className="admin__slot-label">
        <span className={`admin__badge admin__badge--${category}`}>{category}</span>
        {slot.slot}
      </div>
      <select
        className="login-screen__input admin__select"
        value={draft.exerciseId ?? ''}
        onChange={(e) => onPick(e.target.value)}
      >
        <option value="">Choose an exercise…</option>
        {matching.length > 0 && (
          <optgroup label={`Matches ${slot.slot}`}>
            {matching.map((ex) => (
              <option key={ex.id} value={ex.id}>
                {optionLabel(ex, false)}
              </option>
            ))}
          </optgroup>
        )}
        <optgroup label="Other exercises">
          {others.map((ex) => (
            <option key={ex.id} value={ex.id}>
              {optionLabel(ex, true)}
            </option>
          ))}
        </optgroup>
      </select>
      <div className="admin__numbers">
        <label className="admin__field">
          <span>Sets</span>
          <input
            className="login-screen__input"
            type="number"
            inputMode="numeric"
            min={1}
            max={MAX_SETS}
            value={draft.sets}
            onChange={(e) => onChange({ sets: e.target.value })}
          />
        </label>
        <label className="admin__field">
          <span>Reps</span>
          <input
            className="login-screen__input"
            type="number"
            inputMode="numeric"
            min={1}
            max={MAX_REPS}
            value={draft.reps}
            onChange={(e) => onChange({ reps: e.target.value })}
          />
        </label>
      </div>
      {exercise && (
        <small className={`admin__hint${outsideRange ? ' admin__hint--warn' : ''}`}>
          {exercise.min_reps != null && exercise.max_reps != null
            ? `Rep range ${exercise.min_reps}–${exercise.max_reps}${outsideRange ? ' — reps are outside it' : ''}`
            : 'No rep range on file'}
          {exercise.equipment.length > 0 && ` · ${exercise.equipment.join(', ')}`}
        </small>
      )}
      {painful.length > 0 && (
        <small className="admin__hint admin__hint--warn">Loads a painful joint: {painful.join(', ')}</small>
      )}
      {exercise?.avoid_if && <small className="admin__hint">Avoid if: {exercise.avoid_if}</small>}
      <input
        className="login-screen__input admin__note"
        placeholder="Note for this exercise (optional)"
        value={draft.note}
        onChange={(e) => onChange({ note: e.target.value })}
      />
    </div>
  )
}
