"""Cardio circuit days: schedule, timings and weekly progression.

A cardio day is a `sessions` row with kind='cardio' on a day that
DAY_TEMPLATES marks as a rest day (the template itself is left alone — the
workout agent and the coach's planner rely on its rest days). The client runs
the whole `cardio_exercises` circuit `rounds` times, each exercise for
`work_seconds`, and rates the session easy / medium / hard at the end.

Progression is per week, not per session: every cardio session of a plan
shares one level (rounds, work_seconds), and the next plan's level comes
from the ratings of this plan's completed cardio sessions (next_level).

Pure logic only — the repository does the reads and writes.
"""
from collections import Counter
from typing import Iterable, Optional, Tuple

# Which day_numbers get a cardio session, per plan type. They are all rest
# days in DAY_TEMPLATES, so they never clash with a strength session on
# sessions' (plan_id, day_number) unique key.
CARDIO_DAYS = {"3_day": (2, 4, 6), "4_day": (3, 6)}

KIND_STRENGTH = "strength"
KIND_CARDIO = "cardio"

CARDIO_SPLIT_NAME = "Cardio"

# (rounds, seconds per exercise) — everyone starts here.
CARDIO_START = (1, 30)
CARDIO_MIN_SECONDS = 15
CARDIO_MAX_SECONDS = 60
CARDIO_STEP_SECONDS = 10
# What a round is reset to when one is added at CARDIO_MAX_SECONDS.
CARDIO_NEW_ROUND_SECONDS = 30

# On her period (sessions.is_period) each exercise runs this much of its
# planned time — applied when the session is read, so the stored level is
# never changed (see period_seconds).
CARDIO_PERIOD_FACTOR = 0.7

CARDIO_GET_READY_SECONDS = 10
CARDIO_EXERCISE_REST_SECONDS = 20
CARDIO_ROUND_REST_SECONDS = 30

EASY, MEDIUM, HARD = "easy", "medium", "hard"
CARDIO_RATINGS = (EASY, MEDIUM, HARD)
# Ties in the weekly vote go to the more cautious rating.
_CAUTION = {EASY: 0, MEDIUM: 1, HARD: 2}

Level = Tuple[int, int]


def step_up(level: Level) -> Level:
    """+10 s per exercise up to 60 s; past that, one more round at 30 s."""
    rounds, seconds = level
    if seconds < CARDIO_MAX_SECONDS:
        return rounds, min(seconds + CARDIO_STEP_SECONDS, CARDIO_MAX_SECONDS)
    return rounds + 1, CARDIO_NEW_ROUND_SECONDS


def step_down(level: Level) -> Level:
    """-10 s per exercise down to 15 s; below that, one round fewer at 60 s.
    One round at 15 s is the floor."""
    rounds, seconds = level
    if seconds > CARDIO_MIN_SECONDS:
        return rounds, max(seconds - CARDIO_STEP_SECONDS, CARDIO_MIN_SECONDS)
    if rounds > 1:
        return rounds - 1, CARDIO_MAX_SECONDS
    return rounds, CARDIO_MIN_SECONDS


def period_seconds(seconds: int) -> int:
    """Seconds per exercise on a period day: 70% of the plan, to the
    nearest second, never below CARDIO_MIN_SECONDS."""
    return max(CARDIO_MIN_SECONDS, round(seconds * CARDIO_PERIOD_FACTOR))


def actual_work_seconds(session: dict) -> int:
    """The seconds per exercise she actually does in this session."""
    seconds = session["cardio_work_seconds"]
    return period_seconds(seconds) if session.get("is_period") else seconds


def week_outcome(sessions: Iterable[dict]) -> Optional[str]:
    """The week's rating: the most common one among its completed cardio
    sessions, ties going to the harder rating. A completed session that was
    never rated counts as medium. Period sessions ran lighter, so like
    strength progression they never vote. None when no session votes (all
    missed, all on her period, or not yet done)."""
    votes = Counter(
        s.get("cardio_rating") or MEDIUM
        for s in sessions
        if s.get("completed_at") and not s.get("is_period")
    )
    if not votes:
        return None
    return max(votes, key=lambda rating: (votes[rating], _CAUTION[rating]))


def session_level(session: dict) -> Level:
    """The session's planned level — never scaled for a period day."""
    return session["cardio_rounds"], session["cardio_work_seconds"]


def next_level(
    current: Level, outcome: Optional[str], previous_week: Optional[Tuple[str, Level]] = None
) -> Level:
    """Next week's level from this week's outcome.

    easy -> step up; hard -> step down; nothing completed -> hold. medium
    holds once: it steps up only when the previous counted week
    (`previous_week` = (outcome, level)) was also medium at this same level.
    """
    if outcome == EASY:
        return step_up(current)
    if outcome == HARD:
        return step_down(current)
    if outcome == MEDIUM and previous_week == (MEDIUM, tuple(current)):
        return step_up(current)
    return tuple(current)


def estimated_seconds(level: Level, n_exercises: int) -> int:
    """How long the whole circuit takes: the get-ready countdown, every
    exercise of every round, a 20 s rest between exercises and a 30 s rest
    between rounds (in place of the 20 s one)."""
    rounds, seconds = level
    if n_exercises <= 0 or rounds <= 0:
        return 0
    return (
        CARDIO_GET_READY_SECONDS
        + rounds * n_exercises * seconds
        + rounds * (n_exercises - 1) * CARDIO_EXERCISE_REST_SECONDS
        + (rounds - 1) * CARDIO_ROUND_REST_SECONDS
    )


def cardio_day(day: dict) -> dict:
    """A DAY_TEMPLATES day re-labelled as the cardio day it holds."""
    return {**day, "split_name": CARDIO_SPLIT_NAME, "is_rest_day": False, "kind": KIND_CARDIO}


def is_cardio(session: Optional[dict]) -> bool:
    return bool(session) and session.get("kind") == KIND_CARDIO
