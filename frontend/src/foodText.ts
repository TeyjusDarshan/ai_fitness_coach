// Every word on the client's diet screens, in Tamil script. Numbers and the
// units g / kcal stay as they are; ingredient names stay English. The
// one-time setup keeps its own strings (DietSetupScreen).

// Dates on the food screens: "20 நவ., வியாழன்".
const DAY_FORMAT = new Intl.DateTimeFormat('ta-IN', { day: 'numeric', month: 'short', weekday: 'long' })

export function formatTamilDay(iso: string): string {
  const [year, month, day] = iso.split('-').map(Number)
  return DAY_FORMAT.format(new Date(year, month - 1, day))
}

export const TA = {
  // Shared
  back: 'பின்செல்',
  failed: 'ஏதோ தவறு நடந்தது. மீண்டும் முயலுங்கள்.',
  remove: 'நீக்கு',
  removeThing: (name: string) => `${name} நீக்கு`,
  less: (name: string) => `${name} குறைக்க`,
  more: (name: string) => `${name} கூட்ட`,
  about: 'சுமார் ',
  proteinG: (grams: number) => `${grams} g புரதம்`,

  // Your Food
  title: 'உங்கள் உணவு',
  allDays: 'எல்லா நாட்களும்',
  whichDays: 'எந்த நாட்கள்',
  today: 'இன்று',
  pastDays: (n: number) => `கடந்த ${n} நாட்கள்`,
  dailyGoal: 'தினசரி இலக்கு',
  calories: 'கலோரி',
  protein: 'புரதம்',
  fibre: 'நார்ச்சத்து',
  carbs: 'மாவுச்சத்து',
  fat: 'கொழுப்பு',
  beingChecked: 'சரிபார்க்கப்படுகிறது',
  workingOutOne: 'ஒரு பதிவைக் கணக்கிடுகிறோம்…',
  couldNotUnderstandOne: 'ஒரு பதிவைப் புரிந்துகொள்ள முடியவில்லை.',
  // A meal she said she skipped.
  skippedMeal: 'சாப்பிடவில்லை',
  skippedMeals: (meals: string) => `சாப்பிடவில்லை: ${meals}`,
  emptyToday:
    'இன்று இன்னும் எதுவும் பதிவு செய்யவில்லை. மைக்கைத் தட்டி, ஒரு தோழியிடம் சொல்வது போல் என்ன சாப்பிட்டீர்கள் என்று சொல்லுங்கள்: “moonu idli, oru karandi sambar, oru tumbler coffee”.',
  emptyDay: 'இந்த நாளில் எதுவும் பதிவு செய்யப்படவில்லை.',
  overview: 'ஊட்டச்சத்து கண்ணோட்டம்',
  overviewSub: (n: number) => `கடந்த ${n} நாட்களில் நீங்கள் சாப்பிட்டது. ஒரு நாளைத் தட்டினால் அன்று சாப்பிட்டதைப் பார்க்கலாம்.`,
  noLogsYet: 'இன்னும் பதிவு இல்லை',
  average: (text: string) => `சராசரி ${text}`,
  recommended: (text: string) => `பரிந்துரை: ${text}`,
  nothingLogged: 'பதிவு இல்லை',
  record: 'என்ன சாப்பிட்டீர்கள் என்று பதிவு செய்யுங்கள்',
  stopRecording: 'பதிவை நிறுத்து',
  tapToRecord: 'பதிவு செய்ய தட்டவும்',
  listening: (clock: string) => `கேட்கிறோம் ${clock} · நிறுத்த தட்டவும்`,
  sending: 'அனுப்புகிறோம்…',
  sendFailed: 'உங்கள் பதிவை அனுப்ப முடியவில்லை.',
  tryAgain: 'மீண்டும் முயலுங்கள்',
  micBlocked: 'மைக்கைப் பயன்படுத்த முடியவில்லை. உலாவி அமைப்புகளில் மைக் அனுமதியைக் கொடுத்து மீண்டும் முயலுங்கள்.',
  noMic: 'இந்த உலாவியில் ஒலிப்பதிவு செய்ய முடியாது. Chrome அல்லது Safari-யில் திறக்கவும்.',

  // Review (/food/log/:id)
  backToFood: 'உணவுக்குத் திரும்பு',
  workingOut: 'நீங்கள் சாப்பிட்டதைக் கணக்கிடுகிறோம்…',
  workingOutHint: 'இதற்கு சில விநாடிகள் ஆகும். விரும்பினால் பின்செல்லலாம்; இது உங்களுக்காகச் சேமிக்கப்படும்.',
  tryThatAgain: 'மீண்டும் முயலலாம்',
  recordAgain: 'மீண்டும் பதிவு செய்',
  heard: 'நாங்கள் கேட்டது இதுதான்',
  heardLead: 'அளவுகளைச் சரிபாருங்கள். ஒரு உணவைத் தட்டினால் அதில் என்ன சேர்ந்தது என்று பார்க்கலாம்.',
  nothingLeft: 'இந்தப் பதிவில் எதுவும் இல்லை.',
  newDish: 'புதிய உணவு. உங்கள் பயிற்சியாளர் சரிபார்ப்பார்.',
  guessed: 'அளவை நாங்கள் ஊகித்தோம்',
  done: 'முடிந்தது',

  // Dish (/food/item/:id)
  aboutGrams: (grams: number) => ` · சுமார் ${grams} g`,
  couldNotWorkOut: 'இந்த உணவின் பொருட்களைக் கணக்கிட முடியவில்லை. உங்கள் பயிற்சியாளர் சரிபார்ப்பார்.',
  noIngredients: 'இந்த உணவுக்குப் பொருட்கள் எதுவும் இல்லை.',
  assumedLead: 'உங்கள் அளவில் இவை சேர்ந்ததாகக் கணக்கிட்டோம். உங்கள் சமையலில் வேறுபட்டதை மாற்றுங்கள்.',
  putBack: 'திரும்பச் சேர்',
  removed: 'நீக்கப்பட்டது',
  amountOf: (name: string) => `${name} அளவு`,
  changedFrom: (text: string) => `முன்பு ${text}`,
  youChanged: (dish: string) => `இந்த ${dish}-ல் சேர்ந்ததை மாற்றியுள்ளீர்கள்.`,
  resetting: 'மாற்றுகிறோம்…',
  backToEstimate: 'எங்கள் கணக்கிற்குத் திரும்பு',

  // Outside the food screens
  dietTab: 'உணவு',
  entryTitle: 'இன்று என்ன சாப்பிட்டீர்கள்?',
  entryHint: 'உங்கள் சொந்த வார்த்தைகளில் சொல்லுங்கள்',
}
