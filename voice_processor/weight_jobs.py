"""Weight tracking's scheduled work, run every 15 minutes by a systemd timer
on the VM (voice_processor/deploy/weight-jobs.*):

    python -m voice_processor.weight_jobs --due

For each client with diet tracking on and the diet setup done:

1. **Weekly close** (always). Once her Sunday 19:00 has passed (her own
   time zone), the Mon–Sun week just ended is closed once: its average,
   last week's, period days, her food logs over the last 14 days, and the
   streak so far go through diet.weight.rules.decide (the flowcharts). The
   result is a `weight_weeks` row.
   - WEIGHT_WEEKLY_MODE=shadow (the default): stored only (status `shadow`,
     with the calorie number it would propose). Nothing is sent and no
     suggestion is made: the coach checks the rules against real weeks.
   - WEIGHT_WEEKLY_MODE=live: a decision that changes calories becomes a
     pending `nutrition_target_changes` row for the coach (an older pending
     one is superseded), and the Tanglish summary is sent if her 24-hour
     WhatsApp window is open (`skipped_window_closed` otherwise; no
     templates). A week closed more than a day late (the VM was down) is
     stored but not sent (`skipped_late`).
2. **Weigh-in messages**, only with WEIGHT_NUDGES_ENABLED=1, and only while
   her window is open: the one-time how-to (`intro`), and at 10:00 her time
   a nudge if she hasn't sent today's weight (`morning`).

Options: --dry-run (print decisions and texts; nothing stored or sent),
--user-id (one client only).
"""
import argparse
import logging
import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional

from diet.dates import now_in
from diet.nutrition import targets_for
from diet.repository import DietRepository
from diet.service import COUNTED_STATUSES, totals_of
from diet.weight import messages, rules, service, targets
from diet.weight.repository import WeightRepository
from voice_processor.meal_reminders import logged_meals

logger = logging.getLogger(__name__)

CLOSE_AT = time(19, 0)                # Sunday, her time
LATE_AFTER = timedelta(hours=24)      # a later close isn't sent
NUDGE_AT = time(10, 0)
NUDGE_WINDOW_MINUTES = 45
MAIN_MEALS = ("breakfast", "lunch", "dinner")

SHADOW, LIVE = "shadow", "live"
SENT, PENDING, FAILED = "sent", "pending", "failed"
SKIPPED_WINDOW_CLOSED, SKIPPED_LATE, SKIPPED_LOGGED = "skipped_window_closed", "skipped_late", "skipped_logged"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def weekly_mode() -> str:
    return LIVE if os.getenv("WEIGHT_WEEKLY_MODE", SHADOW).strip().lower() == LIVE else SHADOW


def nudges_enabled() -> bool:
    return os.getenv("WEIGHT_NUDGES_ENABLED", "").strip() == "1"


def closing_week(local_now: datetime) -> date:
    """The Monday of the latest week whose Sunday 19:00 has passed."""
    this_start = rules.week_start(local_now.date())
    sunday_close = datetime.combine(this_start + timedelta(days=6), CLOSE_AT, tzinfo=local_now.tzinfo)
    return this_start if local_now >= sunday_close else this_start - timedelta(weeks=1)


def food_gate(logs: List[Dict[str, Any]], start: date, end: date, timezone_name: Optional[str]) -> Dict[str, Any]:
    """Her food logs over start..end: the share of main meals covered
    (logged, or said skipped), and her average logged kcal on the days she
    logged anything."""
    by_day: Dict[str, List[Dict[str, Any]]] = {}
    for log in logs:
        if log.get("status") in COUNTED_STATUSES:
            by_day.setdefault(log["logged_for"], []).append(log)
    days = (end - start).days + 1
    covered = sum(len(logged_meals(day_logs, timezone_name) & set(MAIN_MEALS)) for day_logs in by_day.values())
    totals = [totals_of(day_logs)["energy_kcal"] for day_logs in by_day.values()]
    return {
        "meals_logged": covered,
        "meals_total": days * len(MAIN_MEALS),
        "coverage": round(covered / (days * len(MAIN_MEALS)), 3) if days > 0 else None,
        "avg_kcal": round(sum(totals) / len(totals)) if totals else None,
    }


class Sender:
    """Built lazily, so a dry run never connects to WhatsApp."""

    def __init__(self):
        from whatsapp_client import WhatsAppClient
        self._whatsapp = WhatsAppClient()

    def send(self, phone: str, text: str) -> None:
        self._whatsapp.send_text(phone, text)


def close_week(repo: WeightRepository, diet_repo: DietRepository, client: Dict[str, Any], local_now: datetime,
               get_sender, dry_run: bool = False, mode: Optional[str] = None) -> str:
    """Close her latest finished week once; returns what happened."""
    mode = mode or weekly_mode()
    user_id, tz = client["user_id"], client.get("timezone")
    week = closing_week(local_now)
    week_end = week + timedelta(days=6)
    setup = client.get("diet_setup") or {}
    setup_day = service.local_date(setup.get("completed_at"), tz)
    if setup_day and setup_day > week_end:
        return "before_setup"
    if repo.get_week(user_id, week):
        return "already_closed"

    plan = service.plan_of(client)
    readings = repo.list_readings(user_id, week - timedelta(weeks=1), week_end)
    by_week = service.readings_by_week(readings)
    this, previous = by_week.get(week, []), by_week.get(week - timedelta(weeks=1), [])
    avg, previous_avg = rules.week_average(this), rules.week_average(previous)

    gate_start = week_end - timedelta(days=rules.GATE_DAYS - 1)
    if setup_day and setup_day > gate_start:
        gate_start = setup_day  # a new client: only the days since her setup
    period_week = bool(repo.period_days(user_id, week, week_end))
    gate = food_gate(diet_repo.list_meal_logs(user_id, gate_start, week_end), gate_start, week_end, tz)
    current_targets = targets_for(client.get("nutrition_targets"))
    changes = repo.list_changes(user_id)
    accepted_days = service.accepted_change_days(changes, tz)
    settling = service.settling(week, setup_day, accepted_days)
    previous_rows = [row for row in repo.list_weeks(user_id, limit=8) if row["week_start"] < week.isoformat()]
    last_row = previous_rows[0] if previous_rows else None
    streak = (rules.Streak(last_row["streak"], last_row["streak_stalled"], last_row.get("streak_direction"))
              if last_row else rules.Streak())

    decision = rules.decide(rules.WeekInput(
        goal=plan["goal"], readings=len(this), avg_kg=avg, previous_avg_kg=previous_avg,
        expected_kg=plan["expected_kg"], goal_kg=plan["goal_kg"] if plan["goal"] != "maintain" else None,
        period_week=period_week,
        log_coverage=gate["coverage"], avg_logged_kcal=gate["avg_kcal"],
        target_kcal=current_targets["energy_kcal"], previous_streak=streak,
        settling=settling, change_pending=any(c["status"] == "pending" for c in changes),
    ))

    outcome, new_targets = decision.outcome, None
    if outcome in rules.CHANGE_OUTCOMES:
        person = targets.body(setup, client.get("gender"))
        if outcome == rules.TARGET_REACHED:
            new_targets = targets.maintenance_targets(avg, person)
        else:
            new_targets = targets.changed_targets(current_targets["energy_kcal"], decision.kcal_delta,
                                                  plan["goal"], avg, person)
            if new_targets is None:
                outcome = rules.AT_FLOOR

    after_change = settling == rules.BASELINE and any(rules.week_start(d) == week for d in accepted_days)
    text = messages.weekly_summary(outcome, plan["goal"], {
        "name": client.get("name"), "readings": len(this), "avg_kg": avg, "previous_avg_kg": previous_avg,
        "change_kg": decision.change_kg, "meals_logged": gate["meals_logged"], "meals_total": gate["meals_total"],
        "goal_kg": plan["goal_kg"], "after_change": after_change,
    })

    close_time = datetime.combine(week_end, CLOSE_AT, tzinfo=local_now.tzinfo)
    late = local_now - close_time > LATE_AFTER
    phone = client.get("whatsapp_number")
    if mode == SHADOW:
        status = SHADOW
    elif late:
        status = SKIPPED_LATE
    elif not repo.reply_window_open(phone):
        status = SKIPPED_WINDOW_CLOSED
    else:
        status = PENDING

    if dry_run:
        print(f"{user_id} week {week} ({plan['goal']}): readings={len(this)} avg={avg} prev={previous_avg} "
              f"gate={gate} settling={settling} -> {outcome} {decision.kcal_delta:+d} "
              f"{(new_targets or {}).get('energy_kcal')} [{status}]")
        print("    " + text.replace("\n", "\n    "))
        return outcome

    row = repo.create_week({
        "user_id": user_id, "week_start": week.isoformat(), "goal": plan["goal"], "readings": len(this),
        "avg_kg": avg, "previous_avg_kg": previous_avg, "change_kg": decision.change_kg,
        "expected_kg": plan["expected_kg"], "classification": decision.classification,
        "period_week": period_week,
        "log_coverage": gate["coverage"], "avg_logged_kcal": gate["avg_kcal"],
        "target_kcal": current_targets["energy_kcal"], "outcome": outcome, "kcal_delta": decision.kcal_delta,
        "proposed_kcal": (new_targets or {}).get("energy_kcal"),
        "streak": decision.streak.count, "streak_stalled": decision.streak.stalled,
        "streak_direction": decision.streak.direction, "reason": decision.reason,
        "mode": mode, "message_text": text, "status": status,
    })
    if row is None:
        return "already_closed"

    if mode == LIVE and new_targets:
        repo.supersede_pending(user_id)
        switch = outcome == rules.TARGET_REACHED
        repo.create_change({
            "user_id": user_id, "week_id": row["id"], "source": "goal_switch" if switch else "weekly_rule",
            "from_targets": current_targets, "to_targets": new_targets,
            "new_goal": "maintain" if switch else None, "new_goal_kg": round(avg, 1) if switch else None,
            "reason": decision.reason, "status": "pending",
        })

    if status == PENDING:
        try:
            get_sender().send(phone, text)
        except Exception as error:
            logger.exception("Failed to send the weekly weight summary to user_id=%s", user_id)
            repo.update_week(row["id"], {"status": FAILED, "error": str(error)[:500]})
            return outcome
        repo.update_week(row["id"], {"status": SENT, "sent_at": _now()})
    logger.info("Closed week %s for user_id=%s: %s (%s)", week, user_id, outcome, status)
    return outcome


def _send_nudge(repo: WeightRepository, client: Dict[str, Any], day: date, kind: str, text: str,
                get_sender, dry_run: bool) -> str:
    user_id, phone = client["user_id"], client.get("whatsapp_number")
    if dry_run:
        print(f"{user_id} {kind} nudge: {text}")
        return SENT
    row = repo.create_nudge({"user_id": user_id, "nudge_date": day.isoformat(), "kind": kind, "status": PENDING})
    if row is None:
        return "already_handled"
    try:
        get_sender().send(phone, text)
    except Exception as error:
        logger.exception("Failed to send the %s weigh-in message to user_id=%s", kind, user_id)
        repo.update_nudge(row["id"], {"status": FAILED, "error": str(error)[:500]})
        return FAILED
    repo.update_nudge(row["id"], {"status": SENT, "sent_at": _now()})
    return SENT


def nudge(repo: WeightRepository, client: Dict[str, Any], local_now: datetime, get_sender,
          dry_run: bool = False) -> str:
    """The one-time how-to, then the 10:00 nudge; only while her window is
    open (a closed window is retried on the next run for the how-to, and
    recorded as skipped for the nudge)."""
    user_id, day = client["user_id"], local_now.date()
    window_open = repo.reply_window_open(client.get("whatsapp_number"))
    if not repo.intro_sent(user_id):
        if not window_open:
            return "intro_waiting"
        return _send_nudge(repo, client, day, "intro", messages.intro(client.get("name")), get_sender, dry_run)

    start = datetime.combine(day, NUDGE_AT, tzinfo=local_now.tzinfo)
    if not start <= local_now < start + timedelta(minutes=NUDGE_WINDOW_MINUTES):
        return "not_due"
    if repo.get_nudge(user_id, day, "morning"):
        return "already_handled"
    if repo.has_reading(user_id, day):
        if not dry_run:
            repo.create_nudge({"user_id": user_id, "nudge_date": day.isoformat(), "kind": "morning",
                               "status": SKIPPED_LOGGED})
        return SKIPPED_LOGGED
    if not window_open:
        if not dry_run:
            repo.create_nudge({"user_id": user_id, "nudge_date": day.isoformat(), "kind": "morning",
                               "status": SKIPPED_WINDOW_CLOSED})
        return SKIPPED_WINDOW_CLOSED
    return _send_nudge(repo, client, day, "morning", messages.morning_nudge(client.get("name")), get_sender, dry_run)


def run(repo: WeightRepository, diet_repo: DietRepository, dry_run: bool = False,
        user_id: Optional[str] = None) -> Dict[str, int]:
    sender: Optional[Sender] = None

    def get_sender() -> Sender:
        nonlocal sender
        if sender is None:
            sender = Sender()
        return sender

    counts: Dict[str, int] = {}

    def count(key: str) -> None:
        counts[key] = counts.get(key, 0) + 1

    for client in repo.list_tracked_profiles(user_id):
        local_now = now_in(client.get("timezone"))
        try:
            count("week:" + close_week(repo, diet_repo, client, local_now, get_sender, dry_run))
        except Exception:
            logger.exception("Weekly weight close failed for user_id=%s", client.get("user_id"))
            count("week:failed")
        if nudges_enabled():
            try:
                count("nudge:" + nudge(repo, client, local_now, get_sender, dry_run))
            except Exception:
                logger.exception("Weigh-in nudge failed for user_id=%s", client.get("user_id"))
                count("nudge:failed")
    logger.info("Weight jobs (%s): %s", weekly_mode(), counts)
    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Close weight weeks and send weigh-in nudges.")
    parser.add_argument("--due", action="store_true", help="what's due now by each client's local time (the timer)")
    parser.add_argument("--dry-run", action="store_true", help="print decisions; store and send nothing")
    parser.add_argument("--user-id", help="only this client")
    args = parser.parse_args()
    repo = WeightRepository()
    run(repo, DietRepository(repo.client), dry_run=args.dry_run, user_id=args.user_id)


if __name__ == "__main__":
    main()
