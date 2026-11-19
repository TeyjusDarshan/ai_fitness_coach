// TEMPORARY mock of the diet screens (not for commit): the real FoodScreen,
// MealReviewScreen and MealItemScreen against an in-memory fake API.
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom'
import './index.css'
import './styles/screens.css'
import { AppStateProvider } from './state/AppStateContext'
import { FoodScreen } from './screens/FoodScreen'
import { MealReviewScreen } from './screens/MealReviewScreen'
import { MealItemScreen } from './screens/MealItemScreen'
import { appTodayIso } from './utils'
import { BottomNav } from './components/BottomNav'

type Per100 = { energy_kcal: number; protein_g: number; fibre_g: number; carbs_g: number; fat_g: number }
const REF: Record<string, Per100 & { id: number; unit?: [string, number] }> = {
  'Idli rice': { id: 1, energy_kcal: 348, protein_g: 7.5, fibre_g: 1.5, carbs_g: 79, fat_g: 0.6 },
  'Urad dal': { id: 2, energy_kcal: 327, protein_g: 24, fibre_g: 11, carbs_g: 59.6, fat_g: 1.6 },
  'Toor dal (pigeon pea)': { id: 3, energy_kcal: 317, protein_g: 22.3, fibre_g: 9.1, carbs_g: 57.6, fat_g: 1.7 },
  Tomato: { id: 4, energy_kcal: 19, protein_g: 0.9, fibre_g: 1.2, carbs_g: 3.9, fat_g: 0.2 },
  'Sesame (gingelly) oil': { id: 5, energy_kcal: 900, protein_g: 0, fibre_g: 0, carbs_g: 0, fat_g: 100, unit: ['teaspoon', 5] },
  'Milk (cow/toned)': { id: 6, energy_kcal: 59, protein_g: 3.2, fibre_g: 0, carbs_g: 4.8, fat_g: 3 },
  'Coffee powder (filter coffee blend)': { id: 7, energy_kcal: 338, protein_g: 12, fibre_g: 30, carbs_g: 65, fat_g: 10 },
  'White sugar': { id: 8, energy_kcal: 400, protein_g: 0, fibre_g: 0, carbs_g: 100, fat_g: 0, unit: ['teaspoon', 4] },
  'Raw white rice': { id: 9, energy_kcal: 352, protein_g: 7.1, fibre_g: 1.3, carbs_g: 79.9, fat_g: 0.7 },
  Paneer: { id: 10, energy_kcal: 265, protein_g: 18.3, fibre_g: 0, carbs_g: 1.2, fat_g: 20.8 },
  'Small onion (shallot)': { id: 11, energy_kcal: 72, protein_g: 2.5, fibre_g: 3.2, carbs_g: 16.8, fat_g: 0.1 },
  'Curd (yogurt)': { id: 12, energy_kcal: 63, protein_g: 3.5, fibre_g: 0, carbs_g: 4.7, fat_g: 3.3 },
}
const byId = Object.fromEntries(Object.entries(REF).map(([name, r]) => [r.id, { name, ...r }]))

type Dish = { name: string; meal: string; quantity: number; unit: string; grams: number; ing: [string, number][] }
const DISHES: Dish[] = [
  { name: 'Idli', meal: 'breakfast', quantity: 3, unit: 'piece', grams: 120, ing: [['Idli rice', 40], ['Urad dal', 14]] },
  { name: 'Sambar', meal: 'breakfast', quantity: 1, unit: 'karandi', grams: 50, ing: [['Toor dal (pigeon pea)', 10], ['Tomato', 8], ['Small onion (shallot)', 8], ['Sesame (gingelly) oil', 2]] },
  { name: 'Filter Coffee', meal: 'breakfast', quantity: 1, unit: 'tumbler', grams: 150, ing: [['Milk (cow/toned)', 100], ['Coffee powder (filter coffee blend)', 5], ['White sugar', 8]] },
  { name: 'Cooked Rice', meal: 'lunch', quantity: 2, unit: 'karandi', grams: 120, ing: [['Raw white rice', 42]] },
  { name: 'Paneer Bhurji', meal: 'lunch', quantity: 1, unit: 'cup', grams: 100, ing: [['Paneer', 70], ['Small onion (shallot)', 15], ['Tomato', 15], ['Sesame (gingelly) oil', 5]] },
  { name: 'Curd', meal: 'dinner', quantity: 1, unit: 'cup', grams: 150, ing: [['Curd (yogurt)', 150]] },
]

type Row = { reference_id: number; grams: number; default_grams: number; edited: boolean }
type Item = { id: number; log: number; name: string; meal: string; quantity: number; unit: string; grams: number; assumed: boolean; edited: boolean; rows: Row[] }
type Log = { id: number; date: string; status: string; created: number }
const logs: Log[] = []
const items: Item[] = []
let nextId = 1

const iso = (offset: number) => { const d = new Date(`${appTodayIso()}T00:00:00Z`); d.setUTCDate(d.getUTCDate() - offset); return d.toISOString().slice(0, 10) }
function addLog(date: string, dishes: Dish[], status = 'confirmed') {
  const log = { id: nextId++, date, status, created: Date.now() }
  logs.push(log)
  for (const d of dishes) items.push({
    id: nextId++, log: log.id, name: d.name, meal: d.meal, quantity: d.quantity, unit: d.unit, grams: d.grams,
    assumed: false, edited: false,
    rows: d.ing.map(([n, g]) => ({ reference_id: REF[n].id, grams: g, default_grams: g, edited: false })),
  })
  return log
}
addLog(iso(0), DISHES.slice(0, 3))
for (let i = 1; i < 10; i++) if (i % 4 !== 2) addLog(iso(i), DISHES.slice(i % 3, (i % 3) + 3 + (i % 2)))

const KEYS = ['energy_kcal', 'protein_g', 'fibre_g', 'carbs_g', 'fat_g'] as const
function totalsOf(list: Item[]) {
  const t: Record<string, number> = Object.fromEntries(KEYS.map((k) => [k, 0]))
  for (const it of list) for (const r of it.rows) for (const k of KEYS) t[k] += (byId[r.reference_id][k] * r.grams) / 100
  return Object.fromEntries(KEYS.map((k) => [k, Math.round(t[k] * 10) / 10]))
}
const TARGETS = { energy_kcal: 1800, protein_g: 50, fibre_g: 25, carbs_g: 225, fat_g: 60 }
const shapeItem = (it: Item, detail = false) => {
  const t = totalsOf([it])
  return {
    id: it.id, name: it.name, meal: it.meal, quantity: it.quantity, unit: it.unit, grams: it.grams,
    assumed: it.assumed, needs_review: false, edited: it.edited,
    protein_g: t.protein_g, fibre_g: t.fibre_g, energy_kcal: Math.round(t.energy_kcal),
    ...(detail ? {
      meal_log_id: it.log, logged_for: logs.find((l) => l.id === it.log)!.date,
      ingredients: it.rows.map((r) => ({
        ingredient_id: r.reference_id, name: byId[r.reference_id].name, grams: r.grams, default_grams: r.default_grams,
        edited: r.edited, display_unit: byId[r.reference_id].unit?.[0] ?? null, grams_per_display_unit: byId[r.reference_id].unit?.[1] ?? null,
      })).sort((a, b) => b.default_grams - a.default_grams),
    } : {}),
  }
}
const status = (l: Log) => (l.status === 'processing' && Date.now() - l.created > 3000 ? 'ready' : l.status)
const shapeLog = (l: Log) => ({
  id: l.id, logged_for: l.date, status: status(l), error: null, created_at: new Date(l.created).toISOString(),
  items: status(l) === 'processing' ? [] : items.filter((i) => i.log === l.id).map((i) => shapeItem(i)),
})
const counted = (date: string) => logs.filter((l) => l.date === date && ['ready', 'confirmed'].includes(status(l)))
  .flatMap((l) => items.filter((i) => i.log === l.id))

function handle(method: string, path: string, body: Record<string, number>): unknown {
  let m
  if (path === '/api/auth/me') return { user_id: 'u1', name: 'Test client', gender: 'female', diet_enabled: true }
  if ((m = path.match(/^\/api\/users\/u1\/diet\/days/))) {
    const n = Number(new URLSearchParams(path.split('?')[1]).get('days') ?? 10)
    return { targets: TARGETS, days: Array.from({ length: n }, (_, i) => ({ date: iso(i), totals: totalsOf(counted(iso(i))), dishes: counted(iso(i)).length })) }
  }
  if (path.startsWith('/api/users/u1/diet')) {
    const date = new URLSearchParams(path.split('?')[1]).get('date') ?? iso(0)
    return { date, totals: totalsOf(counted(date)), targets: TARGETS, logs: logs.filter((l) => l.date === date && l.status !== 'discarded').map(shapeLog) }
  }
  if (method === 'POST' && path === '/api/meal-logs') {
    const pick = [...DISHES].sort(() => Math.random() - 0.5).slice(0, 2)
    const log = addLog(iso(0), pick, 'processing')
    return { id: log.id, status: 'processing', logged_for: iso(0) }
  }
  if ((m = path.match(/^\/api\/meal-logs\/(\d+)(\/confirm)?$/))) {
    const log = logs.find((l) => l.id === Number(m![1]))!
    if (method === 'DELETE') { log.status = 'discarded'; return { deleted: true } }
    if (m[2]) { log.status = 'confirmed'; return { id: log.id, status: 'confirmed' } }
    if (log.status === 'processing' && status(log) === 'ready') log.status = 'ready'
    return shapeLog(log)
  }
  if ((m = path.match(/^\/api\/meal-log-items\/(\d+)(\/reset|\/ingredients\/(\d+))?$/))) {
    const it = items.find((i) => i.id === Number(m![1]))!
    if (method === 'DELETE' && !m[2]) { items.splice(items.indexOf(it), 1); return { deleted: true } }
    if (method === 'PATCH' && !m[2]) {
      const ratio = body.quantity / it.quantity
      it.quantity = body.quantity; it.grams = Math.round(it.grams * ratio * 10) / 10; it.edited = true; it.assumed = false
      it.rows.forEach((r) => { r.grams = Math.round(r.grams * ratio * 100) / 100; r.default_grams = Math.round(r.default_grams * ratio * 100) / 100 })
    }
    if (m[2] === '/reset') it.rows.forEach((r) => { r.grams = r.default_grams; r.edited = false })
    if (m[3]) { const r = it.rows.find((x) => x.reference_id === Number(m![3]))!; r.grams = body.grams; r.edited = true; it.edited = true }
    return shapeItem(it, true)
  }
  return {}
}

window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = new URL(String(input), location.origin)
  const method = (init?.method ?? 'GET').toUpperCase()
  const body = typeof init?.body === 'string' ? JSON.parse(init.body) : {}
  await new Promise((r) => setTimeout(r, 150))
  const result = handle(method, url.pathname + url.search, body)
  return new Response(JSON.stringify(result), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

function Home() {
  const navigate = useNavigate()
  return (
    <div className="screen">
      <h1 className="screen-title">Workouts (mock)</h1>
      <p>This stands in for the real dashboard. Use the bar below to switch to Diet.</p>
      <button className="btn-primary" onClick={() => navigate('/food')}>Open Your Food</button>
    </div>
  )
}

createRoot(document.getElementById('root')!).render(
  <MemoryRouter initialEntries={[new URLSearchParams(location.search).get('start') ?? '/']}>
    <AppStateProvider>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/food" element={<FoodScreen />} />
        <Route path="/food/log/:logId" element={<MealReviewScreen />} />
        <Route path="/food/item/:itemId" element={<MealItemScreen />} />
      </Routes>
      <BottomNav />
    </AppStateProvider>
  </MemoryRouter>,
)

if (new URLSearchParams(location.search).get('tab') === 'past') setTimeout(() => (document.querySelectorAll('[role=tab]')[1] as HTMLElement | undefined)?.click(), 800)
