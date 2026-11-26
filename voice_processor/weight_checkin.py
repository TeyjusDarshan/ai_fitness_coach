"""A WhatsApp message the router labelled `weight_checkin` (a text or a
voice note; Haiku read the number) -> her reading for today, and a reply:

- a usable number close to her recent readings -> saved (a later reading
  the same day replaces the earlier one) -> "Noted ✅ 72.4 kg";
- more than 2 kg from her last 7 days' average -> not saved -> "this might
  not be right, check the scale and send it again";
- no usable number (30–200 kg) -> "send just the number".

Her day is her own (user_profiles.timezone)."""
import logging
from typing import Any, Optional

from diet.dates import today_in
from diet.weight import messages, service
from diet.weight.repository import WeightRepository

logger = logging.getLogger(__name__)


def handle(repo: WeightRepository, whatsapp, user_id: str, phone_number: str, weight_kg: Any,
           message_type: str, raw: str, inbound_id: Optional[int], timezone_name: Optional[str]) -> Optional[int]:
    """Save the reading and reply; returns the weight_logs id, or None when
    nothing was saved."""
    source = "whatsapp_voice" if message_type == "audio" else "whatsapp_text"
    status, weight, row = service.record_reading(
        repo, user_id, weight_kg, source, today_in(timezone_name), inbound_message_id=inbound_id, raw=raw,
    )
    if status == service.SAVED:
        reply = messages.noted(weight)
    elif status == service.OUTLIER:
        reply = messages.outlier(weight)
    else:
        reply = messages.no_number()
    logger.info("Weight check-in from user_id=%s: %s %s", user_id, status, weight)
    try:
        whatsapp.send_text(phone_number, reply)
    except Exception:
        logger.exception("Failed to send the weight reply to %s", phone_number)
    return row["id"] if row else None
