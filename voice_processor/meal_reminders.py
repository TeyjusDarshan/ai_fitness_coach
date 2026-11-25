"""Meal reminders: three times a day, at 11:00, 15:00 and 20:00 in each
client's own time zone (user_profiles.timezone), a short text (at most 10
words, Tanglish) on WhatsApp to each diet-tracking client who hasn't logged the meals due so
far.

A systemd timer on the VM (voice_processor/deploy/) runs this every 15
minutes:

    python -m voice_processor.meal_reminders --due

For each client, a slot is due while her local time is between the slot's
time and DUE_WINDOW_MINUTES after it, so she's reminded within 15 minutes of
11:00 / 15:00 / 20:00 her time, and a run missed by more than that is
skipped rather than sent late. `--slot breakfast|lunch|dinner` runs one
slot for everyone now (manual runs). Options: --dry-run (print each decision
and the text; nothing stored or sent), --user-id (one client only).

For each client with diet tracking on and the diet setup done, for the due slot:
1. Already handled this slot on her local date (a meal_reminders row) -> skip.
2. Missing = the meals due by this slot (SLOT_MEALS) minus the meals she
   has logged today. A meal already logged is never asked about again.
   Nothing missing -> `skipped_logged`.
3. Her WhatsApp 24-hour window (whatsapp_reply_windows) closed, or she has
   never messaged -> `skipped_window_closed` (only paid templates could be
   sent then).
4. Otherwise the row is saved first (`pending`, so a crash can't lead to a
   second send), the text is sent -> `sent`, or
   `failed` with the error; the run carries on with the next client.

Her answer comes back through the router (voice_processor/router.py), which
is told about a reminder sent in the last few hours.
"""
import argparse
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set

from diet.dates import now_in, zone
from voice_processor.repository import AnalysisRepository

logger = logging.getLogger(__name__)

MEALS = ("breakfast", "lunch", "snack", "dinner")
SLOT_MEALS = {
    "breakfast": ["breakfast"],
    "lunch": ["breakfast", "lunch"],
    "dinner": ["breakfast", "lunch", "snack", "dinner"],
}
# When each slot's reminder goes out, in the client's own time zone.
SLOT_TIMES = {"breakfast": time(11, 0), "lunch": time(15, 0), "dinner": time(20, 0)}
# How long after a slot's time it still counts as due (the timer runs every
# 15 minutes; a longer gap means the VM was down, and a late reminder is
# worse than none).
DUE_WINDOW_MINUTES = 45

# How a meal is said in the text.
MEAL_WORDS = {"breakfast": "breakfast", "lunch": "lunch", "snack": "snacks", "dinner": "dinner"}

SENT, SKIPPED_LOGGED, SKIPPED_WINDOW_CLOSED, FAILED, PENDING = (
    "sent", "skipped_logged", "skipped_window_closed", "failed", "pending",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def due_slot(local_now: datetime) -> Optional[str]:
    """The slot due at this local time, if any."""
    for slot, at in SLOT_TIMES.items():
        start = local_now.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
        if start <= local_now < start + timedelta(minutes=DUE_WINDOW_MINUTES):
            return slot
    return None


def meal_by_time(created_at: str, timezone_name: Optional[str] = None) -> str:
    """The meal a dish with no meal tag counts as, by when it was logged in
    her time zone: before 11:00 breakfast, before 16:00 lunch, before 19:00
    snack, else dinner."""
    hour = datetime.fromisoformat(created_at).astimezone(zone(timezone_name)).hour
    if hour < 11:
        return "breakfast"
    if hour < 16:
        return "lunch"
    if hour < 19:
        return "snack"
    return "dinner"


def logged_meals(logs: Iterable[Dict[str, Any]], timezone_name: Optional[str] = None) -> Set[str]:
    """The meals covered by her worked-out logs for the day: each dish's
    meal, and every meal she said she skipped ("breakfast skip pannitten"
    answers the breakfast question too)."""
    meals: Set[str] = set()
    for log in logs:
        meals.update(log.get("skipped_meals") or [])
        for item in log.get("meal_log_items") or []:
            meals.add(item.get("meal") or meal_by_time(log["created_at"], timezone_name))
    return meals


def missing_meals(slot: str, logged: Set[str]) -> List[str]:
    return [meal for meal in SLOT_MEALS[slot] if meal not in logged]


def reminder_text(name: Optional[str], missing: List[str]) -> str:
    """'Priya, breakfast, lunch innum log pannala 🙂': at most 10 words
    (name + up to four meals + three)."""
    meals = ", ".join(MEAL_WORDS[meal] for meal in missing)
    greeting = f"{name.strip()}, " if name and name.strip() else ""
    return f"{greeting}{meals} innum log pannala 🙂"


class Sender:
    """Sends one reminder text. Built lazily, so a dry run or a run where
    nobody needs a reminder never connects to WhatsApp."""

    def __init__(self):
        from whatsapp_client import WhatsAppClient
        self._whatsapp = WhatsAppClient()

    def send(self, phone: str, text: str) -> None:
        self._whatsapp.send_text(phone, text)


def remind_client(
    repo: AnalysisRepository, client: Dict[str, Any], slot: str, day: date,
    get_sender, dry_run: bool = False,
) -> str:
    """Handle one client for one slot on her local date `day`; returns what
    happened."""
    user_id = client["user_id"]
    if repo.get_meal_reminder(user_id, day, slot):
        return "already_handled"

    logs = repo.list_counted_meal_logs(user_id, day)
    missing = missing_meals(slot, logged_meals(logs, client.get("timezone")))
    phone = client.get("whatsapp_number")
    window = repo.reply_window(phone) if missing and phone else None
    if not missing:
        status = SKIPPED_LOGGED
    elif not window or not window.get("window_open"):
        # No number on file, never messaged, or her 24-hour window is closed.
        status = SKIPPED_WINDOW_CLOSED
    else:
        status = SENT
    text = reminder_text(client.get("name"), missing) if status == SENT else None

    if dry_run:
        print(f"{user_id} ({client.get('timezone')}, {day}, {slot}): missing={missing} "
              f"window_open={bool(window and window.get('window_open'))} -> {status}")
        if text:
            print(f"    {text}")
        return status

    base = {"user_id": user_id, "reminder_date": day.isoformat(), "slot": slot, "missing_meals": missing}
    if status != SENT:
        repo.create_meal_reminder({**base, "status": status, "error": None if phone else "no WhatsApp number"})
        return status

    row = repo.create_meal_reminder({**base, "status": PENDING})
    if row is None:
        return "already_handled"
    try:
        get_sender().send(phone, text)
    except Exception as error:
        logger.exception("Failed to send the %s reminder to user_id=%s", slot, user_id)
        repo.update_meal_reminder(row["id"], {"status": FAILED, "error": str(error)[:500]})
        return FAILED
    repo.update_meal_reminder(row["id"], {"status": SENT, "sent_at": _now()})
    logger.info("Sent the %s reminder to user_id=%s (missing %s)", slot, user_id, missing)
    return SENT


def run(
    repo: AnalysisRepository, slot: Optional[str] = None, dry_run: bool = False, user_id: Optional[str] = None,
) -> Dict[str, int]:
    """One run for every recipient; returns a count per outcome. With
    `slot`, that slot for everyone now; without, each client's due slot by
    her local time (none due -> `not_due`)."""
    sender: Optional[Sender] = None

    def get_sender() -> Sender:
        nonlocal sender
        if sender is None:
            sender = Sender()
        return sender

    counts: Dict[str, int] = {}
    for client in repo.list_reminder_recipients(user_id):
        try:
            local_now = now_in(client.get("timezone"))
            client_slot = slot or due_slot(local_now)
            if client_slot is None:
                outcome = "not_due"
                if dry_run:
                    print(f"{client['user_id']} ({client.get('timezone')}, {local_now:%H:%M}): no slot due")
            else:
                outcome = remind_client(repo, client, client_slot, local_now.date(), get_sender, dry_run)
        except Exception:
            logger.exception("Meal reminder failed for user_id=%s", client.get("user_id"))
            outcome = FAILED
        counts[outcome] = counts.get(outcome, 0) + 1
    logger.info("Meal reminders (%s): %s", slot or "due", counts)
    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Send WhatsApp meal reminders.")
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--due", action="store_true", help="each client's due slot by her local time (the timer)")
    which.add_argument("--slot", choices=sorted(SLOT_MEALS), help="this slot for everyone, now")
    parser.add_argument("--dry-run", action="store_true", help="print decisions; store and send nothing")
    parser.add_argument("--user-id", help="only this client")
    args = parser.parse_args()
    run(AnalysisRepository(), slot=args.slot, dry_run=args.dry_run, user_id=args.user_id)


if __name__ == "__main__":
    main()
