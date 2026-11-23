"""A client's WhatsApp number and time zone (user_profiles.whatsapp_number,
user_profiles.timezone), checked the same way by the intake
(POST /api/admin/users/profile) and the Monitor edit
(PATCH /api/admin/users/<user_id>/contact)."""
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Asia/Kolkata"
# Country code + number, digits only (what WhatsApp sends as `from`).
WHATSAPP_NUMBER_PATTERN = re.compile(r"^[1-9][0-9]{7,14}$")


class ContactError(ValueError):
    pass


def clean_whatsapp_number(value: Any) -> str:
    """"+971 50-123 4567" -> "971501234567"; ContactError if it isn't a
    full international number."""
    if not isinstance(value, str):
        raise ContactError("'whatsapp_number' is required: country code and number, e.g. 919876543210.")
    digits = re.sub(r"[\s+\-()]", "", value)
    if not WHATSAPP_NUMBER_PATTERN.match(digits):
        raise ContactError("'whatsapp_number' must be the country code and number, e.g. 919876543210.")
    return digits


def clean_timezone(value: Any) -> str:
    """An IANA time zone name such as "Asia/Dubai"; ContactError otherwise."""
    if not isinstance(value, str) or not value.strip() or "/" not in value:
        raise ContactError("'timezone' must be a time zone name such as Asia/Kolkata.")
    try:
        ZoneInfo(value.strip())
    except (ZoneInfoNotFoundError, ValueError):
        raise ContactError(f"Unknown time zone '{value}'.")
    return value.strip()


def is_duplicate_number_error(error: Exception) -> bool:
    text = str(error)
    return "whatsapp_number" in text and ("duplicate key" in text or "23505" in text)

