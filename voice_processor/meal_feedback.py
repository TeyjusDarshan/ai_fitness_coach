"""Feedback on a WhatsApp food check-in (voice_processor/router.py): instead
of a bare "Noted", a short text with the numbers for the meal(s) she just
logged against that meal's share of her daily targets (MEAL_SHARES).

Each meal in the message is judged on its own, using everything she has
logged for that meal today (two messages about one lunch are judged
together). Every macro is shown as eaten / target with ✅ (within its
tolerance band, TOLERANCE, a fraction of the meal's share), 🔻 (short) or
🔺 (over). For a client whose goal is to gain weight, calories are over only
past GAIN_KCAL_OVER. A last line lists the meals she hasn't logged yet today.
A meal she said she skipped gets a gentle nudge; a meal with a dish we
couldn't work out (needs_review, so no nutrients) isn't judged.

Fixed Tanglish templates: no AI call, no voice note, nothing stored. Only
today's logs get feedback — food logged for yesterday still gets "Noted".
"""
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from diet.nutrition import DEFAULT_TARGETS, add_totals, empty_totals, targets_for
from voice_processor.meal_reminders import logged_meals, meal_by_time

logger = logging.getLogger(__name__)

MEALS = ("breakfast", "lunch", "snack", "dinner")
# Each meal's share of her daily targets.
MEAL_SHARES = {"breakfast": 0.25, "lunch": 0.35, "snack": 0.10, "dinner": 0.30}
# How far (as a fraction of the meal's share) a macro may be off before it's
# called out. Fat and fibre estimates from a voice note are the roughest.
TOLERANCE = {"energy_kcal": 0.10, "protein_g": 0.10, "carbs_g": 0.15, "fat_g": 0.20, "fibre_g": 0.20}
# Calories over, for a client trying to gain weight, only past this.
GAIN_KCAL_OVER = 0.30
COUNTED_STATUSES = ("ready", "confirmed")

SHORT, OVER = "short", "over"
ON_TRACK, OFF, SKIPPED, UNKNOWN = "on_track", "off", "skipped", "unknown"

MEAL_WORDS = {"breakfast": "Breakfast", "lunch": "Lunch", "snack": "Snacks", "dinner": "Dinner"}
MACRO_ROWS = (("energy_kcal", "Kcal", ""), ("protein_g", "Protein", " g"), ("carbs_g", "Carbs", " g"),
              ("fat_g", "Fat", " g"), ("fibre_g", "Fibre", " g"))
STATUS_EMOJI = {None: "✅", SHORT: "🔻", OVER: "🔺"}

TOOK_NOTE = "Noted 👍"
HEADER = "{name}, {meals} 👇"
ALL_GOOD = "Ellam correct-a irukku, keep it up 💪"
NOT_LOGGED = "Innum log pannala: {meals}"
SKIPPED_TEXT = ("{meals} skip pannirukeenga. Meals skip pannama, konjam-aavadhu saapdunga — "
                "adutha meal-la nalla saapdunga 🙏")
UNKNOWN_TEXT = ("{meals}-la oru dish-a correct-a kanakku panna mudiyala. "
                "App-la Diet section-la adha sari pannunga.")


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
    """SHORT / OVER for one macro of one meal, or None when it's fine."""
    if expected <= 0:
        return None
    tolerance = TOLERANCE[macro]
    if eaten < expected * (1 - tolerance):
        return SHORT
    if macro == "energy_kcal" and goal == "gain":
        tolerance = max(tolerance, GAIN_KCAL_OVER)
    if eaten > expected * (1 + tolerance):
        return OVER
    return None


def judge_meal(
    meal: str, day_logs: List[Dict[str, Any]], targets: Dict[str, float], goal: Optional[str],
    timezone_name: Optional[str] = None,
) -> Dict[str, Any]:
    """{meal, status, flags: {macro: level}, dishes, eaten, expected} for one meal, from all
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
    expected = {macro: float(targets[macro]) * MEAL_SHARES[meal] for macro in DEFAULT_TARGETS}
    flags = {}
    for macro in DEFAULT_TARGETS:
        level = judge_macro(totals[macro], expected[macro], macro, goal)
        if level:
            flags[macro] = level
    return {"meal": meal, "status": OFF if flags else ON_TRACK, "flags": flags, "dishes": dishes,
            "eaten": {macro: float(totals[macro] or 0) for macro in DEFAULT_TARGETS}, "expected": expected}


def judge_log(
    log: Dict[str, Any], day_logs: List[Dict[str, Any]], stored_targets: Optional[Dict[str, Any]],
    goal: Optional[str], timezone_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """A verdict per meal this check-in talked about."""
    targets = targets_for(stored_targets)
    return [judge_meal(meal, day_logs, targets, goal, timezone_name) for meal in meals_in_log(log, timezone_name)]


def _meal_block(verdict: Dict[str, Any]) -> str:
    """'Lunch' then a line per macro: 'Protein 14 / 20 g 🔻'."""
    lines = [MEAL_WORDS[verdict["meal"]]]
    for macro, label, unit in MACRO_ROWS:
        eaten, expected = round(verdict["eaten"][macro]), round(verdict["expected"][macro])
        lines.append(f"{label} {eaten} / {expected}{unit} {STATUS_EMOJI[verdict['flags'].get(macro)]}")
    return "\n".join(lines)


def compose(
    verdicts: List[Dict[str, Any]], name: Optional[str] = None, not_logged: Optional[List[str]] = None,
) -> str:
    """The reply: a block of numbers per judged meal, the skipped and
    unworked-out meals, and the meals not logged yet today."""
    judged = [verdict for verdict in verdicts if verdict["status"] in (ON_TRACK, OFF) and "eaten" in verdict]
    by_status: Dict[str, List[str]] = {}
    for verdict in verdicts:
        by_status.setdefault(verdict["status"], []).append(MEAL_WORDS[verdict["meal"]])
    parts = []
    if judged:
        meals = _join([MEAL_WORDS[verdict["meal"]].lower() for verdict in judged])
        parts.append(HEADER.format(name=name, meals=meals) if name else TOOK_NOTE)
        parts += [_meal_block(verdict) for verdict in judged]
        if all(verdict["status"] == ON_TRACK for verdict in judged):
            parts.append(ALL_GOOD)
    else:
        parts.append(TOOK_NOTE)
    if by_status.get(SKIPPED):
        parts.append(SKIPPED_TEXT.format(meals=_join(by_status[SKIPPED])))
    if by_status.get(UNKNOWN):
        parts.append(UNKNOWN_TEXT.format(meals=_join(by_status[UNKNOWN])))
    if not_logged:
        parts.append(NOT_LOGGED.format(meals=_join([MEAL_WORDS[meal] for meal in not_logged])))
    return "\n\n".join(parts)


def build_feedback(
    log: Dict[str, Any], day_logs: List[Dict[str, Any]], stored_targets: Optional[Dict[str, Any]],
    goal: Optional[str], timezone_name: Optional[str] = None, name: Optional[str] = None,
) -> Dict[str, Any]:
    """{text, verdicts}."""
    verdicts = judge_log(log, day_logs, stored_targets, goal, timezone_name)
    logged = logged_meals([entry for entry in day_logs if entry.get("status") in COUNTED_STATUSES],
                          timezone_name)
    not_logged = [meal for meal in MEALS if meal not in logged]
    return {"text": compose(verdicts, name, not_logged), "verdicts": verdicts}


def send_feedback(
    diet_repo: Any, whatsapp: Any, meal_log_id: int, user_id: str, phone_number: str,
    timezone_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Work out and text the reply to one of today's ready WhatsApp
    check-ins. Nothing but the send time is stored."""
    log = diet_repo.get_meal_log_detail(meal_log_id)
    day = date.fromisoformat(str(log["logged_for"]))
    day_logs = diet_repo.list_meal_logs(user_id, day, day)
    basics = diet_repo.get_profile_basics(user_id) or {}
    goal = (basics.get("diet_setup") or {}).get("goal")
    feedback = build_feedback(
        log, day_logs, diet_repo.get_targets(user_id), goal, timezone_name, name=basics.get("name"),
    )
    whatsapp.send_text(phone_number, feedback["text"])
    try:
        diet_repo.update_meal_log(meal_log_id, {"feedback_sent_at": _now()})
    except Exception:
        logger.exception("Failed to record that meal feedback was sent for meal_log_id=%s", meal_log_id)
    logger.info("Meal feedback for meal_log_id=%s sent: %s", meal_log_id,
                [(verdict["meal"], verdict["status"]) for verdict in feedback["verdicts"]])
    return feedback


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
