import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, assessDietSetup, completeDietSetup } from '../api'
import { Icon } from '../components/Icon'
import { WheelPicker } from '../components/WheelPicker'
import { useAppState } from '../state/AppStateContext'
import type { BmiCategory, DietGoal, DietSetupAssessment, DietSetupResult } from '../types'

const range = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, i) => from + i)
const HEIGHTS = range(120, 220)
const WEIGHTS = range(30, 200)
const AGES = range(15, 90)

// Every word she sees here, in Tamil.
const TA = {
  title: 'உங்கள் உணவுத் திட்டம்',
  intro: 'உங்களுக்கான தினசரி உணவு இலக்கைக் கணக்கிட மூன்று கேள்விகள்.',
  height: 'உங்கள் உயரம் என்ன?',
  weight: 'உங்கள் எடை என்ன?',
  age: 'உங்கள் வயது என்ன?',
  cm: 'செ.மீ',
  kg: 'கி.கி',
  years: 'வயது',
  next: 'அடுத்து',
  back: 'பின்செல்',
  calculate: 'கணக்கிடு',
  working: 'கணக்கிடுகிறோம்…',
  yourBmi: 'உங்கள் BMI',
  category: { underweight: 'குறைந்த எடை', healthy: 'சரியான எடை', overweight: 'அதிக எடை' } as Record<BmiCategory, string>,
  recommend: {
    lose: 'நீங்கள் எடையைக் குறைக்க வேண்டியிருக்கலாம் என்று நினைக்கிறோம். சரியா?',
    gain: 'நீங்கள் எடையைக் கூட்ட வேண்டியிருக்கலாம் என்று நினைக்கிறோம். சரியா?',
    maintain: 'நீங்கள் இதே எடையைப் பராமரிக்கலாம் என்று நினைக்கிறோம். சரியா?',
  } as Record<DietGoal, string>,
  yes: 'ஆம், சரி',
  no: 'இல்லை',
  choose: 'உங்கள் இலக்கைத் தேர்ந்தெடுங்கள்',
  goal: { lose: 'எடை குறைக்க', gain: 'எடை கூட்ட', maintain: 'இதே எடையைப் பராமரிக்க' } as Record<DietGoal, string>,
  daily: 'உங்கள் தினசரி இலக்கு',
  why: {
    lose: (kcal: number) => `எடை பாதுகாப்பாகக் குறைய, உங்கள் தேவையை விட தினமும் ${kcal} கலோரி குறைவு.`,
    gain: (kcal: number) => `ஆரோக்கியமாக எடை கூட, உங்கள் தேவையை விட தினமும் ${kcal} கலோரி அதிகம்.`,
    maintain: () => 'இதே எடையில் இருக்க, உங்கள் தினசரி தேவை அளவு.',
  } as Record<DietGoal, (kcal: number) => string>,
  kcal: 'கலோரி',
  protein: 'புரதம்',
  carbs: 'மாவுச்சத்து',
  fat: 'கொழுப்பு',
  fibre: 'நார்ச்சத்து',
  start: 'கண்காணிக்கத் தொடங்குங்கள்',
  failed: 'ஏதோ தவறு நடந்தது. மீண்டும் முயலுங்கள்.',
}

type Step = 'height' | 'weight' | 'age' | 'confirm' | 'choose' | 'result'
const QUESTION_STEPS: Step[] = ['height', 'weight', 'age']

// The one-time diet setup, shown the first time she opens Diet: height,
// weight and age on scroll wheels -> her BMI and the goal we recommend, which
// she confirms or changes -> her daily goals -> the tracking screen.
export function DietSetupScreen() {
  const navigate = useNavigate()
  const { userId, markDietSetupDone } = useAppState()
  const [step, setStep] = useState<Step>('height')
  const [height, setHeight] = useState(155)
  const [weight, setWeight] = useState(60)
  const [age, setAge] = useState(35)
  const [assessment, setAssessment] = useState<DietSetupAssessment | null>(null)
  const [result, setResult] = useState<DietSetupResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const inputs = { height_cm: height, weight_kg: weight, age }

  const finish = () => {
    markDietSetupDone()
    navigate('/food', { replace: true })
  }

  const run = async (work: () => Promise<void>) => {
    if (!userId || busy) return
    setBusy(true)
    setError(null)
    try {
      await work()
    } catch (err) {
      // Already done (another tab, a double tap): straight to tracking.
      if (err instanceof ApiError && err.status === 409) finish()
      else setError(TA.failed)
    } finally {
      setBusy(false)
    }
  }

  const calculate = () =>
    run(async () => {
      setAssessment(await assessDietSetup(userId!, inputs))
      setStep('confirm')
    })

  const save = (goal: DietGoal) =>
    run(async () => {
      setResult(await completeDietSetup(userId!, { ...inputs, goal }))
      setStep('result')
    })

  const back = () => {
    setError(null)
    if (step === 'height') navigate('/')
    else if (step === 'weight') setStep('height')
    else if (step === 'age') setStep('weight')
    else if (step === 'confirm') setStep('age')
    else if (step === 'choose') setStep('confirm')
  }

  const questionIndex = QUESTION_STEPS.indexOf(step)
  const wheel = {
    height: { question: TA.height, values: HEIGHTS, value: height, set: setHeight, unit: TA.cm },
    weight: { question: TA.weight, values: WEIGHTS, value: weight, set: setWeight, unit: TA.kg },
    age: { question: TA.age, values: AGES, value: age, set: setAge, unit: TA.years },
  }[step as 'height' | 'weight' | 'age']

  return (
    <div className="screen diet-setup" lang="ta">
      {step !== 'result' && (
        <button className="back-link" onClick={back} disabled={busy}>
          <Icon name="chevronLeft" size={18} />
          {TA.back}
        </button>
      )}
      <h1 className="screen-title diet-setup__title">{TA.title}</h1>

      {wheel && (
        <>
          <div className="diet-setup__dots" aria-hidden="true">
            {QUESTION_STEPS.map((s, i) => (
              <span key={s} className={`diet-setup__dot${i <= questionIndex ? ' diet-setup__dot--on' : ''}`} />
            ))}
          </div>
          {step === 'height' && <p className="diet-setup__intro">{TA.intro}</p>}
          <h2 className="diet-setup__question">{wheel.question}</h2>
          <WheelPicker
            key={step}
            label={wheel.question}
            values={wheel.values}
            value={wheel.value}
            onChange={wheel.set}
            unit={wheel.unit}
          />
          <button
            className="btn-primary diet-setup__action"
            disabled={busy}
            onClick={() => (step === 'age' ? calculate() : setStep(step === 'height' ? 'weight' : 'age'))}
          >
            {step === 'age' ? (busy ? TA.working : TA.calculate) : TA.next}
          </button>
        </>
      )}

      {(step === 'confirm' || step === 'choose') && assessment && (
        <div className="card diet-setup__card">
          <p className="diet-setup__label">{TA.yourBmi}</p>
          <p className="diet-setup__bmi">
            {assessment.bmi.toFixed(1)}
            <span className={`diet-setup__category diet-setup__category--${assessment.bmi_category}`}>
              {TA.category[assessment.bmi_category]}
            </span>
          </p>
          {step === 'confirm' ? (
            <>
              <p className="diet-setup__recommend">{TA.recommend[assessment.recommended_goal]}</p>
              <div className="diet-setup__choices diet-setup__choices--row">
                <button className="btn-secondary" disabled={busy} onClick={() => setStep('choose')}>
                  {TA.no}
                </button>
                <button className="btn-primary" disabled={busy} onClick={() => save(assessment.recommended_goal)}>
                  {busy ? TA.working : TA.yes}
                </button>
              </div>
            </>
          ) : (
            <>
              <p className="diet-setup__recommend">{TA.choose}</p>
              <div className="diet-setup__choices">
                {assessment.allowed_goals.map((goal) => (
                  <button key={goal} className="diet-setup__goal" disabled={busy} onClick={() => save(goal)}>
                    {TA.goal[goal]}
                    <Icon name="chevronRight" size={18} />
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {step === 'result' && result && (
        <>
          <div className="card diet-setup__card">
            <p className="diet-setup__label">{TA.daily}</p>
            <p className="diet-setup__kcal">
              {result.targets.energy_kcal.toLocaleString('en-IN')}
              <span>{TA.kcal}</span>
            </p>
            <p className="diet-setup__why">{TA.why[result.goal](Math.abs(result.adjustment_kcal))}</p>
            <div className="diet-setup__macros">
              {(
                [
                  [TA.protein, result.targets.protein_g],
                  [TA.carbs, result.targets.carbs_g],
                  [TA.fat, result.targets.fat_g],
                  [TA.fibre, result.targets.fibre_g],
                ] as const
              ).map(([label, grams]) => (
                <div key={label} className="diet-setup__macro">
                  <span className="diet-setup__macro-value">{grams} g</span>
                  <span className="diet-setup__macro-label">{label}</span>
                </div>
              ))}
            </div>
          </div>
          <button className="btn-primary diet-setup__action" onClick={finish}>
            {TA.start}
          </button>
        </>
      )}

      {error && <div className="error-banner">{error}</div>}
    </div>
  )
}
