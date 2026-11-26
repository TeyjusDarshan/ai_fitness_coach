"""Weight tracking rules (pure, no I/O): checking a reading, weekly
averages, and the weekly calorie decision for each goal.

`decide` is the three flowcharts in the vault's Weekly Weight Tracking Plan
(lose / gain / maintain), checked in the same order. Every threshold is a
named constant here.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional, Sequence

# --- a single reading ------------------------------------------------------

MIN_KG, MAX_KG = 30, 200
# A reading this far from her 7-day average isn't saved; she's asked to check.
OUTLIER_KG = 2.0
OUTLIER_LOOKBACK_DAYS = 7

# --- a week ----------------------------------------------------------------

# Fewer readings than this in a Mon–Sun week: no average, no decision.
MIN_READINGS = 4
# A change in weekly average smaller than this either way is flat (water).
FLAT_KG = 0.2
# On track = at least this share of the expected weekly change.
ON_TRACK_SHARE = 0.5
# Losing more than this share of body weight in a week is too fast.
LOSE_TOO_FAST_SHARE = 0.01
# Gaining more than this in a week is too fast (mostly fat).
GAIN_TOO_FAST_KG = 0.5
# Maintain: a weekly change at least this big is drift.
MAINTAIN_DRIFT_KG = 0.25
# Within this of her target weight counts as reached.
TARGET_REACHED_KG = 0.5
# Maintain band shown on her gauge: ± this share of the weight she keeps.
MAINTAIN_BAND_SHARE = 0.025
# Expected weekly change when her setup gave none (floors left no room).
DEFAULT_EXPECTED_KG = 0.25

# --- food-log gate (last GATE_DAYS days) -------------------------------------

GATE_DAYS = 14
MIN_LOG_COVERAGE = 0.70
KCAL_GATE_SHARE = 0.10

# --- calorie changes ---------------------------------------------------------

LOSE_SLOW_CUT = -100
LOSE_STALLED_CUT = -150
LOSE_TOO_FAST_RAISE = 150
GAIN_SLOW_RAISE = 150
GAIN_TOO_FAST_CUT = -100
MAINTAIN_STEP = 100
# The week of a calorie change is a baseline, the week after a cool-down.
COOL_DOWN_WEEKS = 2

GOALS = ("lose", "gain", "maintain")

# Outcomes (weight_weeks.outcome).
NOT_ENOUGH_DATA = "not_enough_data"
BASELINE = "baseline"
COOL_DOWN = "cool_down"
CHANGE_PENDING = "change_pending"
TARGET_REACHED = "target_reached"
TOO_FAST = "too_fast"
ON_TRACK = "on_track"
PERIOD_WEEK = "period_week"
LOGS_LOW = "logs_low"
LOGS_OVER = "logs_over"
LOGS_UNDER = "logs_under"
LOGS_OFF = "logs_off"
WAIT = "wait"
LOWER = "lower_calories"
RAISE = "raise_calories"
# Set by the caller when a cut would go below her floor.
AT_FLOOR = "at_floor"

# Outcomes that propose a calorie change for the coach.
CHANGE_OUTCOMES = (TOO_FAST, LOWER, RAISE, TARGET_REACHED)

# Week classifications (weight_weeks.classification).
SLOW, STALLED, DRIFT_UP, DRIFT_DOWN = "slow", "stalled", "drift_up", "drift_down"


def validate_weight(value) -> Optional[float]:
    """A weight in kg rounded to 0.1, or None if it isn't a usable number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or not MIN_KG <= value <= MAX_KG:
        return None
    return round(float(value), 1)


def is_outlier(weight: float, recent: Sequence[float]) -> bool:
    """More than OUTLIER_KG from the average of her recent readings. With no
    recent readings nothing is an outlier."""
    if not recent:
        return False
    return abs(weight - sum(recent) / len(recent)) > OUTLIER_KG


def week_start(day: date) -> date:
    """The Monday of the week `day` is in."""
    return day - timedelta(days=day.weekday())


def week_average(weights: Sequence[float]) -> Optional[float]:
    """The week's average, or None with fewer than MIN_READINGS readings."""
    if len(weights) < MIN_READINGS:
        return None
    return round(sum(weights) / len(weights), 2)


def maintain_band(center_kg: float) -> dict:
    spread = center_kg * MAINTAIN_BAND_SHARE
    return {"center_kg": round(center_kg, 1), "lower_kg": round(center_kg - spread, 1),
            "upper_kg": round(center_kg + spread, 1)}


def toward_goal(goal: str, change_kg: Optional[float], avg_kg: Optional[float],
                band: Optional[dict] = None) -> Optional[bool]:
    """Whether this week moved her toward her goal (green) or not (grey).
    Maintain: inside her band."""
    if goal == "maintain":
        if avg_kg is None or not band:
            return None
        return band["lower_kg"] <= avg_kg <= band["upper_kg"]
    if change_kg is None:
        return None
    return change_kg < 0 if goal == "lose" else change_kg > 0


@dataclass
class Streak:
    """Consecutive counted weeks that call for a change: how many, whether
    any was stalled (lose), and which way she drifted (maintain)."""
    count: int = 0
    stalled: bool = False
    direction: Optional[str] = None


@dataclass
class WeekInput:
    goal: str
    readings: int
    avg_kg: Optional[float]
    previous_avg_kg: Optional[float]
    expected_kg: Optional[float]           # magnitude per week, from her setup
    goal_kg: Optional[float]               # lose / gain target
    period_week: bool
    log_coverage: Optional[float]
    avg_logged_kcal: Optional[float]
    target_kcal: float
    previous_streak: Streak = field(default_factory=Streak)
    # "baseline" (first week after setup or a calorie change) or
    # "cool_down" (the week after that), else None.
    settling: Optional[str] = None
    change_pending: bool = False


@dataclass
class Decision:
    outcome: str
    kcal_delta: int = 0
    classification: Optional[str] = None
    change_kg: Optional[float] = None
    streak: Streak = field(default_factory=Streak)
    reason: str = ""


def _food_gate(week: WeekInput) -> Optional[str]:
    """The food-log outcome that blocks a change, or None when her logs can
    be trusted."""
    if week.log_coverage is None or week.log_coverage < MIN_LOG_COVERAGE or week.avg_logged_kcal is None:
        return LOGS_LOW
    kcal, target = week.avg_logged_kcal, week.target_kcal
    if week.goal == "lose" and kcal > target * (1 + KCAL_GATE_SHARE):
        return LOGS_OVER
    if week.goal == "gain" and kcal < target * (1 - KCAL_GATE_SHARE):
        return LOGS_UNDER
    if week.goal == "maintain" and abs(kcal - target) > target * KCAL_GATE_SHARE:
        return LOGS_OFF
    return None


def decide(week: WeekInput) -> Decision:
    """One closed week -> the outcome, in the flowchart's order."""
    keep = week.previous_streak
    if week.avg_kg is None:
        return Decision(NOT_ENOUGH_DATA, streak=keep, reason=f"Only {week.readings} readings.")
    if week.previous_avg_kg is None:
        return Decision(BASELINE, streak=Streak(), reason="No average last week to compare with.")
    change = round(week.avg_kg - week.previous_avg_kg, 2)
    expected = week.expected_kg or DEFAULT_EXPECTED_KG

    def hold(outcome, reason, streak=keep, classification=None):
        return Decision(outcome, change_kg=change, streak=streak, classification=classification, reason=reason)

    def settling_or_pending() -> Optional[Decision]:
        if week.settling:
            return hold(week.settling, "New plan settling in.", Streak())
        if week.change_pending:
            return hold(CHANGE_PENDING, "A calorie change is waiting for the coach.")
        return None

    if week.goal == "lose":
        if week.goal_kg is not None and week.avg_kg <= week.goal_kg + TARGET_REACHED_KG:
            return hold(TARGET_REACHED, "Reached her target weight.", Streak())
        loss = -change
        if loss > week.avg_kg * LOSE_TOO_FAST_SHARE:
            return Decision(TOO_FAST, LOSE_TOO_FAST_RAISE, TOO_FAST, change, Streak(),
                            "Lost more than 1% of body weight in a week.")
        blocked = settling_or_pending()
        if blocked:
            return blocked
        if loss >= expected * ON_TRACK_SHARE:
            return hold(ON_TRACK, "Lost at least half the expected amount.", Streak(), ON_TRACK)
        classification = SLOW if loss >= FLAT_KG else STALLED
    elif week.goal == "gain":
        if week.goal_kg is not None and week.avg_kg >= week.goal_kg - TARGET_REACHED_KG:
            return hold(TARGET_REACHED, "Reached her target weight.", Streak())
        blocked = settling_or_pending()
        if blocked:
            return blocked
        if change > GAIN_TOO_FAST_KG:
            return Decision(TOO_FAST, GAIN_TOO_FAST_CUT, TOO_FAST, change, Streak(),
                            "Gained more than 0.5 kg in a week.")
        if change >= expected * ON_TRACK_SHARE:
            return hold(ON_TRACK, "Gained at least half the expected amount.", Streak(), ON_TRACK)
        classification = SLOW
    else:
        blocked = settling_or_pending()
        if blocked:
            return blocked
        if abs(change) < MAINTAIN_DRIFT_KG:
            return hold(ON_TRACK, "Steady.", Streak(), ON_TRACK)
        classification = DRIFT_UP if change > 0 else DRIFT_DOWN

    if week.period_week:
        return hold(PERIOD_WEEK, "Period days logged this week; doesn't count.", classification=classification)
    gate = _food_gate(week)
    if gate:
        return hold(gate, "Her food logs can't be trusted to judge calories.", classification=classification)

    if week.goal == "lose":
        if keep.count >= 1:
            stalled = keep.stalled or classification == STALLED
            delta = LOSE_STALLED_CUT if stalled else LOSE_SLOW_CUT
            return Decision(LOWER, delta, classification, change, Streak(),
                            "Two weeks with no real loss." if stalled else "Two slow weeks.")
        return hold(WAIT, "First slow or stalled week.", Streak(1, classification == STALLED), classification)
    if week.goal == "gain":
        if keep.count >= 1:
            return Decision(RAISE, GAIN_SLOW_RAISE, classification, change, Streak(), "Two slow weeks.")
        return hold(WAIT, "First slow week.", Streak(1), classification)
    direction = "up" if classification == DRIFT_UP else "down"
    if keep.count >= 1 and keep.direction == direction:
        delta = -MAINTAIN_STEP if direction == "up" else MAINTAIN_STEP
        return Decision(LOWER if delta < 0 else RAISE, delta, classification, change, Streak(),
                        f"Two weeks drifting {direction}.")
    return hold(WAIT, f"First week drifting {direction}.", Streak(1, False, direction), classification)
