// day_number 1-7 maps onto Monday-Sunday (indexed by schedule position).
export const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

// Between-set rest: shown after checking off a set that doesn't yet
// complete the exercise (1:30).
export const REST_BETWEEN_SETS_SECONDS = 90

// Between-exercise rest: shown after "Begin Next Workout", once every set
// of the current exercise is checked off.
export const REST_BETWEEN_EXERCISES_SECONDS = 30

export const USERNAME_STORAGE_KEY = 'fitness-coach:username'

// Coach's WhatsApp number for the "Share session with coach" flow (+91
// 9180190745) — digits only (country code + number, no leading +), as
// required by the wa.me deep-link format.
export const COACH_WHATSAPP_NUMBER = '919180190745'
