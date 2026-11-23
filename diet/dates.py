"""Dates and times shared by the backend and the voice processor (which are
deployed separately): the app's calendar day (APP_TIMEZONE, mirroring
backend/repository/workout_plan_repository.py:app_today) and a client's own
(user_profiles.timezone) for what happens on WhatsApp."""
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def app_zone() -> ZoneInfo:
    return ZoneInfo(os.environ.get("APP_TIMEZONE", "Asia/Kolkata"))


def app_now() -> datetime:
    return datetime.now(app_zone())


def app_today() -> date:
    return app_now().date()


def zone(name: str = None) -> ZoneInfo:
    """A client's time zone (user_profiles.timezone), or the app's default
    when it's missing or unknown."""
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return app_zone()


def now_in(name: str = None) -> datetime:
    """The current time in a client's time zone."""
    return datetime.now(zone(name))


def today_in(name: str = None) -> date:
    """Today's date in a client's time zone."""
    return now_in(name).date()
