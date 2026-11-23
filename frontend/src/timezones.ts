// Time zones for a client's WhatsApp number (user_profiles.timezone): meal
// reminders go out at 11:00 / 15:00 / 20:00 in her zone.

export const DEFAULT_TIMEZONE = 'Asia/Kolkata'

// Country calling code -> its single time zone. Countries spanning several
// zones (1 US/Canada, 61 Australia, 7 Russia, 55 Brazil, …) are left out so
// the coach has to pick one.
const ZONE_BY_CALLING_CODE: Record<string, string> = {
  '91': 'Asia/Kolkata',
  '971': 'Asia/Dubai',
  '966': 'Asia/Riyadh',
  '974': 'Asia/Qatar',
  '968': 'Asia/Muscat',
  '965': 'Asia/Kuwait',
  '973': 'Asia/Bahrain',
  '94': 'Asia/Colombo',
  '65': 'Asia/Singapore',
  '60': 'Asia/Kuala_Lumpur',
  '44': 'Europe/London',
  '353': 'Europe/Dublin',
  '49': 'Europe/Berlin',
  '33': 'Europe/Paris',
  '64': 'Pacific/Auckland',
}

// "+971 50-123 4567" -> "971501234567".
export function cleanWhatsAppNumber(value: string): string {
  return value.replace(/[\s+\-()]/g, '')
}

export function isValidWhatsAppNumber(value: string): boolean {
  return /^[1-9][0-9]{7,14}$/.test(cleanWhatsAppNumber(value))
}

// The zone a number's country code implies, or null when it's ambiguous or unknown.
export function zoneForNumber(value: string): string | null {
  const digits = cleanWhatsAppNumber(value)
  for (const length of [3, 2, 1]) {
    const zone = ZONE_BY_CALLING_CODE[digits.slice(0, length)]
    if (zone) return zone
  }
  return null
}

// Every IANA zone the browser knows, for the picker.
export function allTimezones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] }
  const zones = intl.supportedValuesOf?.('timeZone') ?? Object.values(ZONE_BY_CALLING_CODE)
  return zones.includes(DEFAULT_TIMEZONE) ? zones : [DEFAULT_TIMEZONE, ...zones]
}

// Old names some browsers still report, mapped to the name stored on file.
const ZONE_ALIASES: Record<string, string> = {
  'Asia/Calcutta': 'Asia/Kolkata',
  'Asia/Katmandu': 'Asia/Kathmandu',
  'Asia/Saigon': 'Asia/Ho_Chi_Minh',
  'Asia/Rangoon': 'Asia/Yangon',
}

// The time zone her phone is set to (it changes by itself when she lands
// somewhere new), or null if the browser won't say.
export function deviceTimezone(): string | null {
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone
    return zone ? (ZONE_ALIASES[zone] ?? zone) : null
  } catch {
    return null
  }
}

function offsetMinutes(timeZone: string, at: Date): number | null {
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone,
      hourCycle: 'h23',
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
      hour: 'numeric',
      minute: 'numeric',
    }).formatToParts(at)
    const get = (type: string) => Number(parts.find((p) => p.type === type)?.value)
    const local = Date.UTC(get('year'), get('month') - 1, get('day'), get('hour'), get('minute'))
    return Math.round((local - at.getTime()) / 60000)
  } catch {
    return null
  }
}

// Two zone names that keep the same clock all year (e.g. "Asia/Kolkata" and
// "Asia/Calcutta", or two cities in one zone) don't count as a change.
export function sameClock(a: string, b: string): boolean {
  if (a === b) return true
  const now = new Date()
  const later = new Date(now.getTime() + 182 * 24 * 3600 * 1000)
  return [now, later].every((at) => {
    const x = offsetMinutes(a, at)
    return x !== null && x === offsetMinutes(b, at)
  })
}

// A readable name for a zone: "Asia/Kuala_Lumpur" -> "Kuala Lumpur".
export function cityOf(timeZone: string): string {
  return (timeZone.split('/').pop() ?? timeZone).replace(/_/g, ' ')
}
