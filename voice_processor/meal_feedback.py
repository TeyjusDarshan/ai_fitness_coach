"""Feedback on a WhatsApp food check-in (voice_processor/router.py): instead
of a bare "Noted", tell her whether the meal(s) she just logged are on
track for her daily targets.

Each meal in the message is judged on its own, against its share of her
daily targets (MEAL_SHARES), using everything she has logged for that meal
today (two messages about one lunch are judged together). A macro is called
out only outside its tolerance band (TOLERANCE, a fraction of the meal's
share):
- short: any of the five goal macros;
- over: only calories, carbs and fat (OVER_FLAGGED) — more protein or fibre
  is never a problem. For a client whose goal is to gain weight, calories
  are over only past GAIN_KCAL_OVER. Past BIG_OVER it's "romba adhigam"
  instead of "konjam adhigam".
A meal she said she skipped gets a gentle nudge; a meal with a dish we
couldn't work out (needs_review, so no nutrients) isn't judged.

Everything is fixed Tanglish templates, no numbers (she's pointed to the
Diet section of the app for those). Only when a macro is flagged does it
cost anything: Claude Haiku adds one tip (meal_feedback_agent.py) and the
reply is a Sarvam voice note; otherwise it's a free text. Only today's
logs get feedback — food logged for yesterday still gets "Noted".
"""
import logging
import re
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from diet.nutrition import DEFAULT_TARGETS, add_totals, empty_totals, targets_for
from voice_processor import meal_feedback_agent
from voice_processor.meal_reminders import meal_by_time

logger = logging.getLogger(__name__)

MEALS = ("breakfast", "lunch", "snack", "dinner")
# Each meal's share of her daily targets.
MEAL_SHARES = {"breakfast": 0.25, "lunch": 0.35, "snack": 0.10, "dinner": 0.30}
# How far (as a fraction of the meal's share) a macro may be off before it's
# called out. Fat and fibre estimates from a voice note are the roughest.
TOLERANCE = {"energy_kcal": 0.10, "protein_g": 0.10, "carbs_g": 0.15, "fat_g": 0.20, "fibre_g": 0.20}
# Macros called out when over; protein and fibre over are fine.
OVER_FLAGGED = ("energy_kcal", "carbs_g", "fat_g")
# Calories over, for a client trying to gain weight, only past this.
GAIN_KCAL_OVER = 0.30
# Over by more than this -> "romba adhigam" rather than "konjam adhigam".
BIG_OVER = 0.50
COUNTED_STATUSES = ("ready", "confirmed")

SHORT, OVER, BIG = "short", "over", "big_over"
ON_TRACK, OFF, SKIPPED, UNKNOWN = "on_track", "off", "skipped", "unknown"

MEAL_WORDS = {"breakfast": "Breakfast", "lunch": "Lunch", "snack": "Snacks", "dinner": "Dinner"}
MACRO_WORDS = {"energy_kcal": "calories", "protein_g": "protein", "carbs_g": "carbs", "fat_g": "fat",
               "fibre_g": "fibre"}
LEVEL_WORDS = {SHORT: "konjam kammi", OVER: "konjam adhigam", BIG: "romba adhigam"}

TOOK_NOTE = "Noted 👍"
ON_TRACK_TEXT = "{meals} correct-a irukku, you are on track! Keep it up 💪"
ON_TRACK_SHORT = "{meals} correct-a irukku."
SKIPPED_TEXT = ("{meals} skip pannirukeenga. Meals skip pannama, konjam-aavadhu saapdunga — "
                "adutha meal-la nalla saapdunga 🙏")
UNKNOWN_TEXT = ("{meals}-la oru dish-a correct-a kanakku panna mudiyala. "
                "App-la Diet section-la adha sari pannunga.")
APP_POINTER = "Exact numbers-ku app-la Diet section paarunga."


_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]")


def spoken(text: str) -> str:
    """The text for the voice note: emoji left out."""
    return re.sub(r"\s+", " ", _EMOJI_RE.sub("", text)).strip()


def _join(words: List[str]) -> str:
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " & " + words[-1]


def item_meal(item: Dict[str, Any], log: Dict[str, Any], timezone_name: Optional[str]) -> str:
    """The meal a dish counts as: its own tag, else by when it was logged."""
    return item.get("meal") or meal_by_time(log["created_at"], timezone_name)


def meals_in_log(log: Dict[str, Any], timezone_name: Optional[str] = None) -> List[str]:
    """The meals this check-in talked about (dishes and skipped meals), in
    the order of the day."""
    meals = set(log.get("skipped_meals") or [])
    meals.update(item_meal(item, log, timezone_name) for item in log.get("meal_log_items") or [])
    return [meal for meal in MEALS if meal in meals]


def judge_macro(eaten: float, expected: float, macro: str, goal: Optional[str]) -> Optional[str]:
    """SHORT / OVER / BIG for one macro of one meal, or None when it's fine."""
    if expected <= 0:
        return None
    tolerance = TOLERANCE[macro]
    if eaten < expected * (1 - tolerance):
        return SHORT
    if macro not in OVER_FLAGGED:
        return None
    if macro == "energy_kcal" and goal == "gain":
        tolerance = max(tolerance, GAIN_KCAL_OVER)
    if eaten > expected * (1 + BIG_OVER):
        return BIG
    if eaten > expected * (1 + tolerance):
        return OVER
    return None


def judge_meal(
    meal: str, day_logs: List[Dict[str, Any]], targets: Dict[str, float], goal: Optional[str],
    timezone_name: Optional[str] = None,
) -> Dict[str, Any]:
    """{meal, status, flags: {macro: level}, dishes} for one meal, from all
    of the day's counted logs."""
    items = [
        item for log in day_logs if log.get("status") in COUNTED_STATUSES
        for item in log.get("meal_log_items") or [] if item_meal(item, log, timezone_name) == meal
    ]
    dishes = [{"name": item.get("dish_name"), "quantity": item.get("quantity"), "unit": item.get("unit")}
              for item in items]
    if not items:
        skipped = any(meal in (log.get("skipped_meals") or []) for log in day_logs
                      if log.get("status") in COUNTED_STATUSES)
        return {"meal": meal, "status": SKIPPED if skipped else ON_TRACK, "flags": {}, "dishes": []}
    if any(item.get("needs_review") for item in items):
        return {"meal": meal, "status": UNKNOWN, "flags": {}, "dishes": dishes}
    totals = empty_totals()
    for item in items:
        add_totals(totals, item.get("nutrients"))
    flags = {}
    for macro in DEFAULT_TARGETS:
        level = judge_macro(totals[macro], float(targets[macro]) * MEAL_SHARES[meal], macro, goal)
        if level:
            flags[macro] = level
    return {"meal": meal, "status": OFF if flags else ON_TRACK, "flags": flags, "dishes": dishes}


def judge_log(
    log: Dict[str, Any], day_logs: List[Dict[str, Any]], stored_targets: Optional[Dict[str, Any]],
    goal: Optional[str], timezone_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """A verdict per meal this check-in talked about."""
    targets = targets_for(stored_targets)
    return [judge_meal(meal, day_logs, targets, goal, timezone_name) for meal in meals_in_log(log, timezone_name)]


def _meal_line(verdict: Dict[str, Any]) -> str:
    """'Lunch-la protein & fibre konjam kammi, carbs romba adhigam.'"""
    parts = []
    for level in (SHORT, OVER, BIG):
        macros = [MACRO_WORDS[macro] for macro in DEFAULT_TARGETS if verdict["flags"].get(macro) == level]
        if macros:
            parts.append(f"{_join(macros)} {LEVEL_WORDS[level]}")
    return f"{MEAL_WORDS[verdict['meal']]}-la {', '.join(parts)}."


def compose(verdicts: List[Dict[str, Any]], tip: Optional[str] = None) -> str:
    """The reply: a line per off meal, then the on-track, skipped and
    unworked-out meals, then (when something is off) the pointer to the app
    and Haiku's tip."""
    by_status: Dict[str, List[str]] = {}
    for verdict in verdicts:
        by_status.setdefault(verdict["status"], []).append(MEAL_WORDS[verdict["meal"]])
    off = [verdict for verdict in verdicts if verdict["status"] == OFF]
    lines = [TOOK_NOTE]
    lines += [_meal_line(verdict) for verdict in off]
    if by_status.get(ON_TRACK):
        lines.append((ON_TRACK_SHORT if off else ON_TRACK_TEXT).format(meals=_join(by_status[ON_TRACK])))
    if by_status.get(SKIPPED):
        lines.append(SKIPPED_TEXT.format(meals=_join(by_status[SKIPPED])))
    if by_status.get(UNKNOWN):
        lines.append(UNKNOWN_TEXT.format(meals=_join(by_status[UNKNOWN])))
    if off:
        if tip:
            lines.append(tip.strip())
        lines.append(APP_POINTER)
    return " ".join(lines) if off else "\n".join(lines)


def build_feedback(
    log: Dict[str, Any], day_logs: List[Dict[str, Any]], stored_targets: Optional[Dict[str, Any]],
    goal: Optional[str], timezone_name: Optional[str] = None,
    get_tip: Optional[Callable[[List[Dict[str, Any]], Optional[str]], Optional[str]]] = None,
) -> Dict[str, Any]:
    """{text, verdicts, voice, tip}: `voice` (and a tip) only when a macro
    is off. A failed tip leaves it out."""
    verdicts = judge_log(log, day_logs, stored_targets, goal, timezone_name)
    off = [verdict for verdict in verdicts if verdict["status"] == OFF]
    tip = None
    if off and get_tip:
        try:
            tip = get_tip(off, goal)
        except Exception:
            logger.exception("Meal feedback tip failed for meal_log_id=%s; sending without it", log.get("id"))
    return {"text": compose(verdicts, tip), "verdicts": verdicts, "voice": bool(off), "tip": tip}


TTS_FEATURE = "meal_feedback_tts"


def _voice_note(text: str, user_id: str, meal_log_id: int) -> str:
    """Speak the reply with Sarvam; returns the public URL. Imported here so
    on-track replies never touch Sarvam."""
    from voice_processor.voice import generate_voice_note_at
    return generate_voice_note_at(
        spoken(text), f"meal_feedback/{user_id}/meal_{meal_log_id}.ogg",
        {"feature": TTS_FEATURE, "user_id": user_id, "session_id": None},
    )


def send_feedback(
    diet_repo: Any, whatsapp: Any, meal_log_id: int, user_id: str, phone_number: str,
    timezone_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Work out, store (meal_logs.feedback*) and send the reply to one of
    today's ready WhatsApp check-ins. A voice note that can't be made or
    sent falls back to the same text."""
    log = diet_repo.get_meal_log_detail(meal_log_id)
    day = date.fromisoformat(str(log["logged_for"]))
    day_logs = diet_repo.list_meal_logs(user_id, day, day)
    basics = diet_repo.get_profile_basics(user_id) or {}
    goal = (basics.get("diet_setup") or {}).get("goal")
    feedback = build_feedback(
        log, day_logs, diet_repo.get_targets(user_id), goal, timezone_name,
        get_tip=lambda off, goal: meal_feedback_agent.write_tip(off, goal, user_id=user_id),
    )
    # Stored before sending, so a failure after the send can't lead to a
    # second reply from the router's "Noted" fallback.
    diet_repo.update_meal_log(meal_log_id, {
        "feedback": feedback["text"],
        "feedback_flags": {"verdicts": [
            {key: verdict[key] for key in ("meal", "status", "flags")} for verdict in feedback["verdicts"]
        ], "tip": feedback["tip"]},
    })
    sent: Dict[str, Any] = {}
    if feedback["voice"]:
        try:
            audio_url = _voice_note(feedback["text"], user_id, meal_log_id)
            whatsapp.send_audio(phone_number, audio_url)
            sent["feedback_audio_url"] = audio_url
        except Exception:
            logger.exception("Meal feedback voice note failed for meal_log_id=%s; sending text", meal_log_id)
    if not sent:
        whatsapp.send_text(phone_number, feedback["text"])
    sent_as = "audio" if sent else "text"
    try:
        diet_repo.update_meal_log(meal_log_id, {**sent, "feedback_sent_at": _now()})
    except Exception:
        logger.exception("Failed to record that meal feedback was sent for meal_log_id=%s", meal_log_id)
    logger.info("Meal feedback for meal_log_id=%s sent as %s: %s", meal_log_id, sent_as,
                [(verdict["meal"], verdict["status"]) for verdict in feedback["verdicts"]])
    return {**feedback, "sent_as": sent_as}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
