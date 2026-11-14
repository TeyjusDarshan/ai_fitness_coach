import logging
import os
from typing import Tuple

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
        self._graph_url = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
        self._messages_url = f"{self._graph_url}/{phone_number_id}/messages"

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
            "audio": {"link": audio_url},
        })

    def download_media(self, media_id: str) -> Tuple[bytes, str]:
        """(bytes, mime_type) of an inbound message's media, e.g. a voice
        note's audio.id. The Cloud API hands out a short-lived URL for the
        id, which itself needs the bearer token to download.
        """
        headers = {"Authorization": f"Bearer {self._access_token}"}
        meta = requests.get(f"{self._graph_url}/{media_id}", headers=headers, timeout=10)
        meta.raise_for_status()
        info = meta.json()
        media = requests.get(info["url"], headers=headers, timeout=30)
        media.raise_for_status()
        return media.content, info.get("mime_type") or "audio/ogg"

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
