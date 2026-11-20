// Wording and step sizes for the Food screens: how a portion ("3 pieces",
// "½ cup", "100 g") and an ingredient amount ("2 teaspoons", "35 g") are
// shown, and how far one tap on − / + moves them.
import type { MealIngredient, MealItem, MealLogError, MealName } from './types'

// In Tamil (no plural forms): [one, many].
const UNIT_LABELS: Record<string, [string, string]> = {
  piece: ['துண்டு', 'துண்டு'],
  karandi: ['கரண்டி', 'கரண்டி'],
  cup: ['கப்', 'கப்'],
  tumbler: ['டம்ளர்', 'டம்ளர்'],
  tablespoon: ['மேசைக்கரண்டி', 'மேசைக்கரண்டி'],
  teaspoon: ['தேக்கரண்டி', 'தேக்கரண்டி'],
  plate: ['தட்டு', 'தட்டு'],
  bowl: ['கிண்ணம்', 'கிண்ணம்'],
  handful: ['கைப்பிடி', 'கைப்பிடி'],
  slice: ['துண்டு', 'துண்டு'],
}

const FRACTIONS: Record<string, string> = { '0.25': '¼', '0.5': '½', '0.75': '¾' }

// 0.5 -> "½", 1.5 -> "1½", 2 -> "2", 1.3 -> "1.3"
export function formatCount(value: number): string {
  const whole = Math.floor(value)
  const fraction = FRACTIONS[String(Math.round((value - whole) * 100) / 100)]
  if (fraction) return whole > 0 ? `${whole}${fraction}` : fraction
  return String(Math.round(value * 10) / 10)
}

function isWeight(unit: string): boolean {
  return unit === 'grams' || unit === 'ml'
}

function withUnit(amount: number, unit: string): string {
  const [one, many] = UNIT_LABELS[unit] ?? [unit, unit]
  return `${formatCount(amount)} ${amount > 1 ? many : one}`
}

export function portionLabel(item: Pick<MealItem, 'quantity' | 'unit'>): string {
  if (isWeight(item.unit)) return `${Math.round(item.quantity)} ${item.unit === 'ml' ? 'ml' : 'g'}`
  return withUnit(item.quantity, item.unit)
}

// The portion one tap away: quarters below 1, halves above; 25 g steps for
// a weight. Null at the ends of what the server accepts.
export function nextQuantity(item: Pick<MealItem, 'quantity' | 'unit'>, direction: 1 | -1): number | null {
  const { quantity } = item
  if (isWeight(item.unit)) {
    const next = Math.round((quantity + direction * 25) / 25) * 25
    return next >= 25 && next <= 2000 ? next : null
  }
  const step = direction > 0 ? (quantity < 1 ? 0.25 : 0.5) : quantity <= 1 ? 0.25 : 0.5
  const next = Math.round((quantity + direction * step) * 4) / 4
  return next >= 0.25 && next <= 20 ? next : null
}

// Whether an ingredient is shown in its own unit (teaspoons of oil) or grams.
function displayUnit(ingredient: MealIngredient): { unit: string; grams: number } | null {
  return ingredient.display_unit && ingredient.grams_per_display_unit
    ? { unit: ingredient.display_unit, grams: ingredient.grams_per_display_unit }
    : null
}

// An ingredient's amount in the unit it is shown in.
export function ingredientAmount(ingredient: MealIngredient, grams = ingredient.grams): number {
  const display = displayUnit(ingredient)
  if (!display) return grams >= 10 ? Math.round(grams) : Math.round(grams * 10) / 10
  return Math.round((grams / display.grams) * 4) / 4
}

export function ingredientUnitLabel(ingredient: MealIngredient, amount: number): string {
  const display = displayUnit(ingredient)
  if (!display) return 'g'
  const [one, many] = UNIT_LABELS[display.unit] ?? [display.unit, display.unit]
  return amount > 1 ? many : one
}

export function ingredientLabel(ingredient: MealIngredient, grams = ingredient.grams): string {
  const amount = ingredientAmount(ingredient, grams)
  if (!displayUnit(ingredient)) return `${amount} g`
  return `${formatCount(amount)} ${ingredientUnitLabel(ingredient, amount)}`
}

// Grams for an amount typed or stepped in the unit shown.
export function ingredientGrams(ingredient: MealIngredient, amount: number): number {
  const display = displayUnit(ingredient)
  return Math.round(amount * (display ? display.grams : 1) * 100) / 100
}

// One tap on − / +: quarter spoons (or pieces); for grams, finer when small.
export function nextIngredientAmount(ingredient: MealIngredient, direction: 1 | -1): number {
  const amount = ingredientAmount(ingredient)
  if (displayUnit(ingredient)) return Math.max(0, Math.round((amount + direction * 0.25) * 4) / 4)
  const reference = direction > 0 ? amount : amount - 0.01
  const step = reference < 10 ? 1 : reference < 50 ? 5 : 10
  return Math.max(0, Math.round((amount + direction * step) / step) * step)
}

export const MEAL_ORDER: (MealName | null)[] = ['breakfast', 'lunch', 'dinner', 'snack', null]

export const MEAL_LABELS: Record<string, string> = {
  breakfast: 'காலை உணவு',
  lunch: 'மதிய உணவு',
  dinner: 'இரவு உணவு',
  snack: 'சிற்றுண்டி',
  other: 'மற்றவை',
}

// The dish's Tamil name, or the English one for older entries.
export function dishName(item: Pick<MealItem, 'name' | 'name_ta'>): string {
  return item.name_ta || item.name
}

export const MEAL_LOG_ERRORS: Record<MealLogError, string> = {
  no_speech: 'அந்தப் பதிவில் எதுவும் கேட்கவில்லை. போனை அருகில் வைத்து மீண்டும் முயலுங்கள்.',
  no_food: 'நீங்கள் சொன்னதில் உணவு எதுவும் இல்லை. என்ன, எவ்வளவு சாப்பிட்டீர்கள் என்று சொல்லுங்கள்.',
  failed: 'கணக்கிடும்போது ஏதோ தவறு நடந்தது. மீண்டும் பதிவு செய்யுங்கள்.',
  timeout: 'கணக்கிட அதிக நேரம் ஆனது. மீண்டும் பதிவு செய்யுங்கள்.',
}
