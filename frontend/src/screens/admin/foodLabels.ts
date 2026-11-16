// Names and units of the nutrients the diet tracker totals, for the coach's
// screens (the keys are the ingredients table's per-100 g columns).
export const NUTRIENT_LABELS: Record<string, [string, string]> = {
  energy_kcal: ['Energy', 'kcal'],
  protein_g: ['Protein', 'g'],
  carbs_g: ['Carbs', 'g'],
  fibre_g: ['Fibre', 'g'],
  fat_g: ['Fat', 'g'],
  saturated_fat_g: ['Saturated fat', 'g'],
  unsaturated_fat_g: ['Unsaturated fat', 'g'],
  sugar_g: ['Sugar', 'g'],
  calcium_mg: ['Calcium', 'mg'],
  iron_mg: ['Iron', 'mg'],
  sodium_mg: ['Sodium', 'mg'],
  potassium_mg: ['Potassium', 'mg'],
  magnesium_mg: ['Magnesium', 'mg'],
  zinc_mg: ['Zinc', 'mg'],
  vitamin_a_mcg: ['Vitamin A', 'mcg'],
  vitamin_c_mg: ['Vitamin C', 'mg'],
  vitamin_d_mcg: ['Vitamin D', 'mcg'],
  vitamin_b12_mcg: ['Vitamin B12', 'mcg'],
  folate_mcg: ['Folate', 'mcg'],
}

export const MACRO_KEYS = ['energy_kcal', 'protein_g', 'carbs_g', 'fibre_g', 'fat_g', 'saturated_fat_g', 'unsaturated_fat_g']
export const MICRO_KEYS = Object.keys(NUTRIENT_LABELS).filter((key) => !MACRO_KEYS.includes(key))

export function nutrientValue(key: string, value: number | null | undefined): string {
  if (value == null) return '—'
  const rounded = key === 'energy_kcal' || value >= 100 ? Math.round(value) : Math.round(value * 10) / 10
  return `${rounded} ${NUTRIENT_LABELS[key]?.[1] ?? ''}`.trim()
}
