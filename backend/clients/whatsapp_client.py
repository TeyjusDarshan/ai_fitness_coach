import logging
import os

import requests

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v21.0"


class WhatsAppClient:
    """Thin wrapper over the WhatsApp Cloud API (Meta Graph API) for sending
    outbound messages from the business phone number.

    Auth is a bearer access token scoped to the business phone number, both
    provisioned in the Meta developer console.
    """

    def __init__(self):
        self._access_token = os.environ["WHATSAPP_ACCESS_TOKEN"]
        phone_number_id = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
        self._messages_url = (
            f"https://graph.facebook.com/{GRAPH_API_VERSION}/{phone_number_id}/messages"
        )

    def send_text(self, to: str, body: str) -> None:
        self._send({
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body},
        })

    def send_audio(self, to: str, audio_url: str) -> None:
        """audio_url must be a publicly reachable link (e.g. the Supabase
        storage URL produced by workout_analysis_consumer.voice) — the Cloud
        API fetches it server-side rather than accepting an upload here.
        """
        self._send({
            "messaging_product": "whatsapp",
            "to": to,
            "type": "audio",
            "audio": {"link": "https://khwrrvmejvrupokvfwvf.supabase.co/storage/v1/object/public/test_bucket/day_5.ogg"},
        })

    def _send(self, payload: dict) -> None:
        response = requests.post(
            self._messages_url,
            headers={"Authorization": f"Bearer {self._access_token}"},
            json=payload,
            timeout=10,
        )
        if not response.ok:
            logger.error(
                "WhatsApp API call failed: status=%s body=%s", response.status_code, response.text
            )
        response.raise_for_status()
