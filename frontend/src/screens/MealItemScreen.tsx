import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Icon } from '../components/Icon'
import { fetchMealItem, resetMealItemRecipe, setMealItemIngredient } from '../api'
import {
  formatCount,
  ingredientAmount,
  ingredientGrams,
  ingredientLabel,
  ingredientUnitLabel,
  nextIngredientAmount,
  portionLabel,
} from '../food'
import type { MealIngredient, MealItemDetail } from '../types'

const SAVE_DELAY_MS = 600

// One logged dish opened up: every ingredient with the amount assumed for
// her portion. She can change an amount (− / +, or type it) or remove an
// ingredient; that becomes her own version of the dish from then on, and
// "Use the standard recipe" undoes it.
export function MealItemScreen() {
  const navigate = useNavigate()
  const itemId = Number(useParams().itemId)
  const [item, setItem] = useState<MealItemDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [resetting, setResetting] = useState(false)
  // The ingredient whose amount is being typed, and the text so far.
  const [typing, setTyping] = useState<{ id: number; text: string } | null>(null)
  const saveTimers = useRef(new Map<number, number>())

  useEffect(() => {
    let stopped = false
    fetchMealItem(itemId)
      .then((data) => !stopped && setItem(data))
      .catch((e: Error) => !stopped && setError(e.message))
    const timers = saveTimers.current
    return () => {
      stopped = true
      timers.forEach((id) => window.clearTimeout(id))
    }
  }, [itemId])

  function setGrams(ingredient: MealIngredient, grams: number) {
    grams = Math.min(2000, Math.max(0, grams))
    setItem(
      (prev) =>
        prev && {
          ...prev,
          own_recipe: true,
          ingredients: prev.ingredients.map((row) =>
            row.ingredient_id === ingredient.ingredient_id ? { ...row, grams, edited: true } : row,
          ),
        },
    )
    const id = ingredient.ingredient_id
    window.clearTimeout(saveTimers.current.get(id))
    saveTimers.current.set(
      id,
      window.setTimeout(() => {
        saveTimers.current.delete(id)
        setMealItemIngredient(itemId, id, grams)
          .then((saved) => {
            // Other edits still waiting to be sent: keep what she sees.
            if (saveTimers.current.size === 0) setItem((prev) => prev && { ...prev, ...saved })
          })
          .catch((e: Error) => setError(e.message))
      }, SAVE_DELAY_MS),
    )
  }

  function commitTyped(ingredient: MealIngredient) {
    if (!typing || typing.id !== ingredient.ingredient_id) return
    const amount = Number(typing.text.replace(',', '.'))
    setTyping(null)
    if (typing.text.trim() === '' || !Number.isFinite(amount) || amount < 0) return
    setGrams(ingredient, ingredientGrams(ingredient, amount))
  }

  async function reset() {
    setResetting(true)
    saveTimers.current.forEach((id) => window.clearTimeout(id))
    saveTimers.current.clear()
    try {
      const saved = await resetMealItemRecipe(itemId)
      setItem((prev) => prev && { ...prev, ...saved })
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
    setResetting(false)
  }

  if (!item) {
    return (
      <div className="screen food-screen">
        <button className="back-link" onClick={() => navigate(-1)}>
          <Icon name="chevronLeft" size={18} />
          Back
        </button>
        {error ? <div className="error-banner">{error}</div> : <div className="spinner" />}
      </div>
    )
  }

  return (
    <div className="screen food-screen">
      <button className="back-link" onClick={() => navigate(-1)}>
        <Icon name="chevronLeft" size={18} />
        Back
      </button>
      <h1 className="screen-title food-screen__title">{item.name}</h1>
      <p className="food-screen__date">
        {item.assumed ? 'about ' : ''}
        {portionLabel(item)}
        {item.grams !== null && item.unit !== 'grams' ? ` · about ${Math.round(item.grams)} g` : ''}
      </p>
      {error && <div className="error-banner">{error}</div>}

      {item.ingredients.length === 0 ? (
        <p className="food-screen__empty">
          {item.needs_review
            ? "This dish is new to us, so we don't have its ingredients yet. Your coach will check it."
            : 'No ingredients are listed for this dish.'}
        </p>
      ) : (
        <>
          <p className="food-screen__lead">
            This is what we assumed went into your portion. Change anything that is different in your kitchen and
            we&apos;ll remember it for next time.
          </p>
          <div className="card food-ingredients">
            {item.ingredients.map((ingredient) => {
              const removed = ingredient.grams === 0
              const isTyping = typing?.id === ingredient.ingredient_id
              const amount = ingredientAmount(ingredient)
              return (
                <div
                  key={ingredient.ingredient_id}
                  className={`food-ingredient${removed ? ' food-ingredient--removed' : ''}`}
                >
                  <div className="food-ingredient__head">
                    <span className="food-ingredient__name">{ingredient.name}</span>
                    {removed ? (
                      <button className="btn-link" onClick={() => setGrams(ingredient, ingredient.default_grams)}>
                        Put back
                      </button>
                    ) : (
                      <button
                        className="food-ingredient__remove"
                        onClick={() => setGrams(ingredient, 0)}
                        aria-label={`Remove ${ingredient.name}`}
                      >
                        <Icon name="close" size={16} />
                      </button>
                    )}
                  </div>
                  {removed ? (
                    <span className="food-ingredient__note">Removed</span>
                  ) : (
                    <div className="food-stepper food-stepper--ingredient">
                      <button
                        className="food-stepper__button"
                        onClick={() =>
                          setGrams(ingredient, ingredientGrams(ingredient, nextIngredientAmount(ingredient, -1)))
                        }
                        aria-label={`Less ${ingredient.name}`}
                      >
                        <Icon name="minus" size={20} />
                      </button>
                      <label className="food-stepper__field">
                        <input
                          className="food-stepper__input"
                          inputMode="decimal"
                          aria-label={`${ingredient.name} amount`}
                          value={isTyping ? typing.text : formatCount(amount)}
                          onFocus={() => setTyping({ id: ingredient.ingredient_id, text: String(amount) })}
                          onChange={(e) => setTyping({ id: ingredient.ingredient_id, text: e.target.value })}
                          onBlur={() => commitTyped(ingredient)}
                          onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
                        />
                        <span className="food-stepper__unit">{ingredientUnitLabel(ingredient, amount)}</span>
                      </label>
                      <button
                        className="food-stepper__button"
                        onClick={() =>
                          setGrams(ingredient, ingredientGrams(ingredient, nextIngredientAmount(ingredient, 1)))
                        }
                        aria-label={`More ${ingredient.name}`}
                      >
                        <Icon name="plus" size={20} />
                      </button>
                    </div>
                  )}
                  {ingredient.edited && !removed && ingredient.grams !== ingredient.default_grams && (
                    <span className="food-ingredient__note">
                      Changed from {ingredientLabel(ingredient, ingredient.default_grams)}
                    </span>
                  )}
                </div>
              )
            })}
          </div>

          {item.own_recipe && (
            <div className="food-own-recipe">
              <p>This is your own version of {item.name}. We&apos;ll use it whenever you log it.</p>
              <button className="btn-secondary" disabled={resetting} onClick={() => void reset()}>
                {resetting ? 'Resetting…' : 'Use the standard recipe'}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
