"""Weight tracking glue between the rules and the database: saving a
reading, her current plan (goal, target, band), which weeks are settling
after a change, and the view her app and the coach read."""
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from diet.dates import parse_timestamp, zone
from diet.nutrition import targets_for
from diet.weight import rules
from diet.weight.repository import WeightRepository

SAVED, OUTLIER, INVALID = "saved", "outlier", "invalid"

# Her chart's range when the app doesn't ask for one.
DEFAULT_CHART_WEEKS = 8


def local_date(timestamp: Optional[str], timezone_name: Optional[str]) -> Optional[date]:
    if not timestamp:
        return None
    return parse_timestamp(timestamp).astimezone(zone(timezone_name)).date()


def plan_of(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Her goal now, the weight it aims at, where she started and how fast
    she should move. `weight_goal` (set when she reaches a target) wins over
    her diet setup."""
    setup = profile.get("diet_setup") or {}
    setup_goal = setup.get("goal") or "maintain"
    goal = profile.get("weight_goal") or setup_goal
    if profile.get("weight_goal"):
        goal_kg = profile.get("weight_goal_kg")
    elif goal == "maintain":
        goal_kg = setup.get("weight_kg")
    else:
        goal_kg = setup.get("target_weight_kg")
    goal_kg = float(goal_kg) if goal_kg is not None else None
    return {
        "goal": goal,
        "goal_kg": goal_kg,
        "start_kg": float(setup["weight_kg"]) if setup.get("weight_kg") is not None else None,
        "expected_kg": setup.get("weekly_change_kg") if goal == setup_goal and goal != "maintain" else None,
        "band": rules.maintain_band(goal_kg) if goal == "maintain" and goal_kg else None,
    }


def record_reading(repo: WeightRepository, user_id: str, value: Any, source: str, today: date,
                   inbound_message_id: Optional[int] = None, raw: Optional[str] = None
                   ) -> Tuple[str, Optional[float], Optional[Dict[str, Any]]]:
    """(SAVED, kg, row) | (OUTLIER, kg, None) | (INVALID, None, None).
    An outlier (more than 2 kg from her last 7 days' average) isn't saved;
    a second reading the same day replaces the first."""
    weight = rules.validate_weight(value)
    if weight is None:
        return INVALID, None, None
    recent = repo.list_readings(user_id, today - timedelta(days=rules.OUTLIER_LOOKBACK_DAYS), today - timedelta(days=1))
    if rules.is_outlier(weight, [float(row["weight_kg"]) for row in recent]):
        return OUTLIER, weight, None
    row = repo.upsert_reading({
        "user_id": user_id, "measured_on": today.isoformat(), "weight_kg": weight, "source": source,
        "inbound_message_id": inbound_message_id, "raw": raw,
    })
    return SAVED, weight, row


def readings_by_week(readings: List[Dict[str, Any]]) -> Dict[date, List[float]]:
    weeks: Dict[date, List[float]] = {}
    for row in readings:
        day = date.fromisoformat(row["measured_on"])
        weeks.setdefault(rules.week_start(day), []).append(float(row["weight_kg"]))
    return weeks


def settling(week: date, setup_day: Optional[date], accepted_days: List[date]) -> Optional[str]:
    """`baseline` for the week of her setup or of her latest calorie change
    on or before this week, `cool_down` for the week after a change."""
    changes = [rules.week_start(day) for day in accepted_days if rules.week_start(day) <= week]
    if changes:
        latest = max(changes)
        if week == latest:
            return rules.BASELINE
        if week == latest + timedelta(weeks=rules.COOL_DOWN_WEEKS - 1):
            return rules.COOL_DOWN
    if setup_day and week == rules.week_start(setup_day):
        return rules.BASELINE
    return None


def accepted_change_days(changes: List[Dict[str, Any]], timezone_name: Optional[str]) -> List[date]:
    return [local_date(c.get("decided_at") or c["created_at"], timezone_name)
            for c in changes if c["status"] == "accepted"]


def _calorie_marks(changes: List[Dict[str, Any]], timezone_name: Optional[str], since: date) -> List[Dict[str, Any]]:
    marks = []
    for change in changes:
        if change["status"] != "accepted":
            continue
        day = local_date(change.get("decided_at") or change["created_at"], timezone_name)
        if day < since:
            continue
        marks.append({
            "date": day.isoformat(),
            "from_kcal": (change.get("from_targets") or {}).get("energy_kcal"),
            "to_kcal": (change.get("to_targets") or {}).get("energy_kcal"),
        })
    return marks


def view(profile: Dict[str, Any], readings: List[Dict[str, Any]], latest_week: Optional[Dict[str, Any]],
         changes: List[Dict[str, Any]], today: date, chart_weeks: Optional[int]) -> Dict[str, Any]:
    """What her Food card and Weight Trend screen show (and the top of the
    coach's view). `readings` must cover the chart range plus this week;
    `chart_weeks` None = all."""
    plan = plan_of(profile)
    by_day = {row["measured_on"]: float(row["weight_kg"]) for row in readings}
    weeks = readings_by_week(readings)
    this_start = rules.week_start(today)
    last_start = this_start - timedelta(weeks=1)
    this_weights = weeks.get(this_start, [])
    this_avg = round(sum(this_weights) / len(this_weights), 2) if this_weights else None
    last_avg = rules.week_average(weeks.get(last_start, []))
    change = round(this_avg - last_avg, 2) if this_avg is not None and last_avg is not None else None

    closed = sorted(start for start in weeks if start < this_start)
    if chart_weeks:
        closed = [start for start in closed if start >= this_start - timedelta(weeks=chart_weeks)]
    points = [{"week_start": start.isoformat(), "average_kg": rules.week_average(weeks[start]),
               "readings": len(weeks[start])} for start in closed]
    points = [point for point in points if point["average_kg"] is not None]
    unlocked = any(rules.week_average(w) is not None for start, w in weeks.items() if start < this_start)
    chart_since = date.fromisoformat(points[0]["week_start"]) if points else this_start

    return {
        "goal": plan["goal"],
        "start_weight_kg": plan["start_kg"],
        "target_weight_kg": plan["goal_kg"] if plan["goal"] != "maintain" else None,
        "band": plan["band"],
        "today": {"date": today.isoformat(), "weight_kg": by_day.get(today.isoformat())},
        "this_week": {"week_start": this_start.isoformat(), "average_kg": this_avg, "readings": len(this_weights)},
        "last_week": {"week_start": last_start.isoformat(), "average_kg": last_avg,
                      "readings": len(weeks.get(last_start, []))},
        "change_vs_last_week_kg": change,
        "toward_goal": rules.toward_goal(plan["goal"], change, this_avg, plan["band"]),
        "status": ({"week_start": latest_week["week_start"], "outcome": latest_week["outcome"],
                    "classification": latest_week.get("classification")} if latest_week else None),
        "chart": {
            "unlocked": unlocked,
            "readings_needed": 0 if unlocked else max(0, rules.MIN_READINGS - len(this_weights)),
            "unlocks_on": None if unlocked else (this_start + timedelta(days=6)).isoformat(),
            "weeks": points,
        },
        "calorie_changes": _calorie_marks(changes, profile.get("timezone"), chart_since),
        "targets": targets_for(profile.get("nutrition_targets")),
        "timezone": profile.get("timezone"),
    }


def chart_range_start(today: date, chart_weeks: Optional[int], first_reading: Optional[Dict[str, Any]]) -> date:
    """The first day `view` needs readings from."""
    if chart_weeks:
        return rules.week_start(today) - timedelta(weeks=chart_weeks)
    if first_reading:
        return rules.week_start(date.fromisoformat(first_reading["measured_on"]))
    return rules.week_start(today) - timedelta(weeks=1)


def now_local(timezone_name: Optional[str]) -> datetime:
    return datetime.now(zone(timezone_name))
