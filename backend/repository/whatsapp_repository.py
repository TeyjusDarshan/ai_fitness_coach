"""Tracks each client's WhatsApp reply window (`whatsapp_conversations`).

WhatsApp lets the business send free-form (non-template) messages only for
24 hours after the client's last message; our own messages don't extend
it. The webhook records every inbound message here, and
`whatsapp_reply_windows` (a view) says whether the window is open.
"""
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

REPLY_WINDOW_HOURS = 24


class WhatsAppRepository:
    def __init__(self, client: Optional[Client] = None):
        if client is not None:
            self.client = client
        else:
            self.client = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))

    def record_inbound(self, phone_number: str, at: datetime, message_id: Optional[str], message_type: str) -> None:
        """One message from the client. Never moves the window backwards
        (the `record_whatsapp_inbound` function keeps the latest time), and
        links the row to her profile when "91" + user_id matches."""
        self.client.rpc("record_whatsapp_inbound", {
            "p_phone_number": phone_number,
            "p_at": at.isoformat(),
            "p_message_id": message_id,
            "p_type": message_type,
        }).execute()

    def reply_window(self, phone_number: str) -> Optional[Dict[str, Any]]:
        """{phone_number, user_id, last_inbound_at, window_expires_at,
        window_open} for a phone, or None if she has never messaged."""
        rows = (
            self.client.table("whatsapp_reply_windows")
            .select("*")
            .eq("phone_number", phone_number)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None


def message_time(message: Dict[str, Any]) -> datetime:
    """When she sent a webhook message: Meta's `timestamp` (Unix seconds),
    else now."""
    try:
        return datetime.fromtimestamp(int(message["timestamp"]), tz=timezone.utc)
    except (KeyError, TypeError, ValueError):
        return datetime.now(timezone.utc)
