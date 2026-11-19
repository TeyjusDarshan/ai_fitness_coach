// Names and units of the nutrients the diet tracker totals, for the coach's
// screens (the keys are ingredient_nutrition_reference's per-100 g columns).
export const NUTRIENT_LABELS: Record<string, [string, string]> = {
  energy_kcal: ['Energy', 'kcal'],
  protein_g: ['Protein', 'g'],
  carbs_g: ['Carbs', 'g'],
  sugar_g: ['Sugar', 'g'],
  fibre_g: ['Fibre', 'g'],
  soluble_fibre_g: ['Soluble fibre', 'g'],
  insoluble_fibre_g: ['Insoluble fibre', 'g'],
  fat_g: ['Fat', 'g'],
  saturated_fat_g: ['Saturated fat', 'g'],
  monounsaturated_fat_g: ['Monounsaturated fat', 'g'],
  polyunsaturated_fat_g: ['Polyunsaturated fat', 'g'],
  unsaturated_fat_g: ['Unsaturated fat', 'g'],
  trans_fat_g: ['Trans fat', 'g'],
  cholesterol_mg: ['Cholesterol', 'mg'],
  alcohol_g: ['Alcohol', 'g'],
  sodium_mg: ['Sodium', 'mg'],
  potassium_mg: ['Potassium', 'mg'],
  calcium_mg: ['Calcium', 'mg'],
  iron_mg: ['Iron', 'mg'],
  magnesium_mg: ['Magnesium', 'mg'],
  phosphorus_mg: ['Phosphorus', 'mg'],
  zinc_mg: ['Zinc', 'mg'],
  vitamin_a_mcg_rae: ['Vitamin A', 'mcg'],
  vitamin_c_mg: ['Vitamin C', 'mg'],
  vitamin_d_mcg: ['Vitamin D', 'mcg'],
  vitamin_e_mg: ['Vitamin E', 'mg'],
  vitamin_k_mcg: ['Vitamin K', 'mcg'],
  thiamin_b1_mg: ['Thiamin (B1)', 'mg'],
  riboflavin_b2_mg: ['Riboflavin (B2)', 'mg'],
  niacin_b3_mg: ['Niacin (B3)', 'mg'],
  vitamin_b6_mg: ['Vitamin B6', 'mg'],
  folate_mcg: ['Folate', 'mcg'],
  vitamin_b12_mcg: ['Vitamin B12', 'mcg'],
}

export function nutrientValue(key: string, value: number | null | undefined): string {
  if (value == null) return '—'
  const rounded = key === 'energy_kcal' || value >= 100 ? Math.round(value) : Math.round(value * 10) / 10
  return `${rounded} ${NUTRIENT_LABELS[key]?.[1] ?? ''}`.trim()
}
