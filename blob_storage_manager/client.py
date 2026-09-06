import os
from abc import ABC, abstractmethod
from typing import Optional

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()


class BlobStorageManager(ABC):
    """Abstract base for storing raw bytes under a name and getting back a
    URL that can be persisted (e.g. session_day_analysis.audio_url).
    """

    @abstractmethod
    def store(self, data: bytes, name: str) -> str:
        """Store data under name and return a URL it can be fetched from."""
        raise NotImplementedError


class SupabaseBlobStorageManager(BlobStorageManager):
    """BlobStorageManager implementation backed by Supabase Storage."""

    def __init__(self, bucket: str = "voice-notes", client: Optional[Client] = None):
        if client is not None:
            self.client = client
        else:
            url = os.environ["SUPABASE_URL"]
            key = os.environ["SUPABASE_KEY"]
            self.client = create_client(url, key)
        self._bucket = bucket

    def store(self, data: bytes, name: str) -> str:
        self.client.storage.from_(self._bucket).upload(
            name,
            data,
            {"upsert": "true"},
        )
        return self.client.storage.from_(self._bucket).get_public_url(name)
