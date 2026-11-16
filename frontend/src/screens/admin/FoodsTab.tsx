import { Fragment, useEffect, useMemo, useState } from 'react'
import { ApiError } from '../../api'
import {
  fetchFoodLibrary,
  saveFood,
  saveIngredient,
  type FoodLibrary,
  type LibraryFood,
  type LibraryIngredient,
} from '../../adminApi'
import { MACRO_KEYS, NUTRIENT_LABELS } from './foodLabels'

// Coach-only: everything the diet tracker has learned. Dishes (household
// unit weights and the recipe they're built from) and ingredients (nutrients
// per 100 g) are added by Claude the first time a client mentions them;
// here the coach checks them, corrects the numbers and marks them verified.
export function FoodsTab({ adminKey, onUnauthorized }: { adminKey: string; onUnauthorized: () => void }) {
  const [library, setLibrary] = useState<FoodLibrary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<'dishes' | 'ingredients'>('dishes')
  const [open, setOpen] = useState<number | null>(null)
  const [search, setSearch] = useState('')

  useEffect(() => {
    let cancelled = false
    fetchFoodLibrary(adminKey)
      .then((data) => !cancelled && setLibrary(data))
      .catch((err) => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 401) onUnauthorized()
        else setError(err instanceof Error ? err.message : 'Could not load the food library.')
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adminKey])

  const ingredientNames = useMemo(
    () => new Map((library?.ingredients ?? []).map((ingredient) => [ingredient.id, ingredient.name])),
    [library],
  )

  function failed(err: unknown): string {
    if (err instanceof ApiError && err.status === 401) onUnauthorized()
    return err instanceof Error ? err.message : 'Failed to save.'
  }

  if (error) return <div className="error-banner">{error}</div>
  if (!library) return <div className="spinner" />

  const matches = (name: string, aliases: string[]) => {
    const needle = search.trim().toLowerCase()
    return !needle || [name, ...aliases].some((text) => text.toLowerCase().includes(needle))
  }
  const foods = library.foods.filter((food) => matches(food.name, food.aliases))
  const ingredients = library.ingredients.filter((ingredient) => matches(ingredient.name, ingredient.aliases))
  const unverified =
    library.foods.filter((food) => !food.verified).length +
    library.ingredients.filter((ingredient) => !ingredient.verified).length

  return (
    <div className="costs foods">
      <div className="costs__controls">
        <div className="admin__segmented costs__range" role="tablist" aria-label="Dishes or ingredients">
          {(
            [
              ['dishes', `Dishes (${library.foods.length})`],
              ['ingredients', `Ingredients (${library.ingredients.length})`],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={view === key}
              className={`admin__segment${view === key ? ' admin__segment--active' : ''}`}
              onClick={() => {
                setView(key)
                setOpen(null)
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <input
          className="login-screen__input foods__search"
          type="search"
          placeholder="Search by name"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <p className="admin__muted">
        {unverified === 0
          ? 'Everything here has been checked.'
          : `${unverified} still to check. These were estimated by AI the first time a client mentioned them.`}
      </p>

      <section className="card costs__section">
        {view === 'dishes' ? (
          foods.length === 0 ? (
            <p className="admin__muted">No dishes yet. They appear here as clients log their food.</p>
          ) : (
            <div className="costs__scroll">
              <table className="costs__table">
                <thead>
                  <tr>
                    <th>Dish</th>
                    <th>Unit weights</th>
                    <th>Recipe, per 100 g cooked</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {foods.map((food) => (
                    <Fragment key={food.id}>
                      <tr
                        className={`costs__row${open === food.id ? ' costs__row--open' : ''}`}
                        onClick={() => setOpen(open === food.id ? null : food.id)}
                      >
                        <td>
                          <NameCell name={food.name} aliases={food.aliases} expanded={open === food.id} />
                        </td>
                        <td>
                          {Object.entries(food.portions)
                            .map(([unit, grams]) => `${unit} ${grams} g`)
                            .join(', ')}
                        </td>
                        <td>
                          {food.recipe
                            .map((line) => `${ingredientNames.get(line.ingredient_id) ?? '?'} ${line.grams_per_100g} g`)
                            .join(', ')}
                        </td>
                        <td>
                          <Status verified={food.verified} />
                        </td>
                      </tr>
                      {open === food.id && (
                        <tr className="costs__detail">
                          <td colSpan={4}>
                            <FoodEditor
                              food={food}
                              library={library}
                              ingredientNames={ingredientNames}
                              onSave={async (change) => {
                                const saved = await saveFood(adminKey, food.id, change)
                                setLibrary({
                                  ...library,
                                  foods: library.foods.map((other) => (other.id === food.id ? saved : other)),
                                })
                              }}
                              failed={failed}
                            />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : ingredients.length === 0 ? (
          <p className="admin__muted">No ingredients yet.</p>
        ) : (
          <div className="costs__scroll">
            <table className="costs__table">
              <thead>
                <tr>
                  <th>Ingredient, per 100 g raw</th>
                  {MACRO_KEYS.map((key) => (
                    <th key={key} className="costs__num">
                      {NUTRIENT_LABELS[key][0]}
                    </th>
                  ))}
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {ingredients.map((ingredient) => (
                  <Fragment key={ingredient.id}>
                    <tr
                      className={`costs__row${open === ingredient.id ? ' costs__row--open' : ''}`}
                      onClick={() => setOpen(open === ingredient.id ? null : ingredient.id)}
                    >
                      <td>
                        <NameCell
                          name={ingredient.name}
                          aliases={ingredient.aliases}
                          expanded={open === ingredient.id}
                        />
                      </td>
                      {MACRO_KEYS.map((key) => (
                        <td key={key} className="costs__num">
                          {ingredient[key] == null ? '—' : String(ingredient[key])}
                        </td>
                      ))}
                      <td>
                        <Status verified={ingredient.verified} />
                      </td>
                    </tr>
                    {open === ingredient.id && (
                      <tr className="costs__detail">
                        <td colSpan={MACRO_KEYS.length + 2}>
                          <IngredientEditor
                            ingredient={ingredient}
                            nutrients={library.nutrients}
                            onSave={async (change) => {
                              const saved = await saveIngredient(adminKey, ingredient.id, change)
                              setLibrary({
                                ...library,
                                ingredients: library.ingredients.map((other) =>
                                  other.id === ingredient.id ? ({ ...other, ...saved } as LibraryIngredient) : other,
                                ),
                              })
                            }}
                            failed={failed}
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}

function NameCell({ name, aliases, expanded }: { name: string; aliases: string[]; expanded: boolean }) {
  return (
    <button type="button" className="costs__client" aria-expanded={expanded}>
      <span className="costs__caret" aria-hidden>
        {expanded ? '▾' : '▸'}
      </span>
      <span>
        <span className="costs__name">{name}</span>
        {aliases.length > 0 && <span className="costs__id">{aliases.slice(0, 3).join(', ')}</span>}
      </span>
    </button>
  )
}

function Status({ verified }: { verified: boolean }) {
  return verified ? (
    <span className="monitor__chip">Checked</span>
  ) : (
    <span className="monitor__chip monitor__chip--mild">AI estimate</span>
  )
}

function NumberField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="foods__field">
      <span className="monitor__label">{label}</span>
      <input
        className="login-screen__input"
        inputMode="decimal"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  )
}

function SaveRow({
  busy,
  saved,
  error,
  onSave,
}: {
  busy: boolean
  saved: boolean
  error: string | null
  onSave: (verified: boolean) => void
}) {
  return (
    <>
      <div className="monitor__row foods__actions">
        <button type="button" className="btn-secondary" disabled={busy} onClick={() => onSave(true)}>
          {busy ? 'Saving…' : 'Save and mark checked'}
        </button>
        <button type="button" className="btn-link" disabled={busy} onClick={() => onSave(false)}>
          Save, still to check
        </button>
        {saved && <span className="admin__muted">Saved</span>}
      </div>
      {error && <div className="error-banner">{error}</div>}
    </>
  )
}

function FoodEditor({
  food,
  library,
  ingredientNames,
  onSave,
  failed,
}: {
  food: LibraryFood
  library: FoodLibrary
  ingredientNames: Map<number, string>
  onSave: (change: Parameters<typeof saveFood>[2]) => Promise<void>
  failed: (err: unknown) => string
}) {
  const [portions, setPortions] = useState<Record<string, string>>(() =>
    Object.fromEntries(library.portion_units.map((unit) => [unit, food.portions[unit] ? String(food.portions[unit]) : ''])),
  )
  const [recipe, setRecipe] = useState(() =>
    food.recipe.map((line) => ({ ingredient_id: line.ingredient_id, grams: String(line.grams_per_100g) })),
  )
  const [defaultUnit, setDefaultUnit] = useState(food.default_unit)
  const [adding, setAdding] = useState('')
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const unused = library.ingredients.filter((ingredient) => !recipe.some((line) => line.ingredient_id === ingredient.id))

  async function save(verified: boolean) {
    setBusy(true)
    setError(null)
    setSaved(false)
    try {
      await onSave({
        verified,
        default_unit: defaultUnit,
        portions: Object.fromEntries(
          Object.entries(portions)
            .filter(([, grams]) => grams.trim() !== '')
            .map(([unit, grams]) => [unit, Number(grams)]),
        ),
        recipe: recipe
          .filter((line) => line.grams.trim() !== '' && Number(line.grams) > 0)
          .map((line) => ({ ingredient_id: line.ingredient_id, grams_per_100g: Number(line.grams) })),
      })
      setSaved(true)
    } catch (err) {
      setError(failed(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="foods__editor" onClick={(e) => e.stopPropagation()}>
      <h4 className="foods__heading">Weight of one unit, in grams (leave blank if the unit isn&apos;t used)</h4>
      <div className="foods__grid">
        {library.portion_units.map((unit) => (
          <NumberField
            key={unit}
            label={unit}
            value={portions[unit]}
            onChange={(value) => setPortions({ ...portions, [unit]: value })}
          />
        ))}
      </div>
      <label className="foods__field foods__field--wide">
        <span className="monitor__label">Unit assumed when she gives no amount</span>
        <select className="login-screen__input" value={defaultUnit} onChange={(e) => setDefaultUnit(e.target.value)}>
          {library.portion_units
            .filter((unit) => portions[unit].trim() !== '')
            .map((unit) => (
              <option key={unit} value={unit}>
                {unit}
              </option>
            ))}
        </select>
      </label>

      <h4 className="foods__heading">Recipe: raw grams of each ingredient in 100 g of the cooked dish</h4>
      <div className="foods__grid">
        {recipe.map((line, i) => (
          <NumberField
            key={line.ingredient_id}
            label={ingredientNames.get(line.ingredient_id) ?? '?'}
            value={line.grams}
            onChange={(value) => setRecipe(recipe.map((other, j) => (j === i ? { ...other, grams: value } : other)))}
          />
        ))}
      </div>
      <p className="admin__muted">Clear an amount to take that ingredient out.</p>
      {unused.length > 0 && (
        <label className="foods__field foods__field--wide">
          <span className="monitor__label">Add an ingredient</span>
          <select
            className="login-screen__input"
            value={adding}
            onChange={(e) => {
              const id = Number(e.target.value)
              if (id) setRecipe([...recipe, { ingredient_id: id, grams: '' }])
              setAdding('')
            }}
          >
            <option value="">Choose…</option>
            {unused.map((ingredient) => (
              <option key={ingredient.id} value={ingredient.id}>
                {ingredient.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <p className="admin__muted">
        A changed recipe applies to what clients log from now on. A client who has her own version of this dish keeps
        it.
      </p>
      <SaveRow busy={busy} saved={saved} error={error} onSave={(verified) => void save(verified)} />
    </div>
  )
}

function IngredientEditor({
  ingredient,
  nutrients,
  onSave,
  failed,
}: {
  ingredient: LibraryIngredient
  nutrients: string[]
  onSave: (change: Record<string, number | boolean | null>) => Promise<void>
  failed: (err: unknown) => string
}) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(nutrients.map((key) => [key, ingredient[key] == null ? '' : String(ingredient[key])])),
  )
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save(verified: boolean) {
    setBusy(true)
    setError(null)
    setSaved(false)
    try {
      const change: Record<string, number | boolean | null> = { verified }
      for (const key of nutrients) {
        const text = values[key].trim()
        // A blank macro is left as it was; a blank micronutrient means unknown.
        if (text === '' && MACRO_KEYS.includes(key)) continue
        change[key] = text === '' ? null : Number(text)
      }
      await onSave(change)
      setSaved(true)
    } catch (err) {
      setError(failed(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="foods__editor" onClick={(e) => e.stopPropagation()}>
      <h4 className="foods__heading">Per 100 g, raw. Changing these updates every day already logged.</h4>
      <div className="foods__grid">
        {nutrients.map((key) => (
          <NumberField
            key={key}
            label={`${NUTRIENT_LABELS[key]?.[0] ?? key} (${NUTRIENT_LABELS[key]?.[1] ?? ''})`}
            value={values[key]}
            onChange={(value) => setValues({ ...values, [key]: value })}
          />
        ))}
      </div>
      <SaveRow busy={busy} saved={saved} error={error} onSave={(verified) => void save(verified)} />
    </div>
  )
}
