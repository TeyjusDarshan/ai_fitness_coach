import os
from abc import ABC, abstractmethod
from typing import Optional

from dotenv import load_dotenv
from supabase import Client, create_client
from storage3.types import FileOptions

load_dotenv()


class BlobStorageManager(ABC):
    """Abstract base for storing raw bytes under a name and getting back a
    URL that can be persisted (e.g. session_day_analysis.audio_url).
    """

    @abstractmethod
    def store(self, data: bytes, name: str, content_type: str = "audio/ogg") -> str:
        """Store data under name and return a URL it can be fetched from
        (only meaningful for a public bucket; see create_signed_url)."""
        raise NotImplementedError

    @abstractmethod
    def create_signed_url(self, name: str, expires_in: int) -> str:
        """A temporary URL for a stored object, valid for expires_in seconds
        — the way to read from a private bucket."""
        raise NotImplementedError

    @abstractmethod
    def remove(self, name: str) -> None:
        """Delete a stored object."""
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

    def store(self, data: bytes, name: str, content_type: str = "audio/ogg") -> str:
        self.client.storage.from_(self._bucket).upload(
            path=name,
            file=data,
            file_options=FileOptions(
                **{"content-type": content_type},
                upsert="true"
            ),
        )
        return self.client.storage.from_(self._bucket).get_public_url(name)

    def create_signed_url(self, name: str, expires_in: int) -> str:
        return self.client.storage.from_(self._bucket).create_signed_url(name, expires_in)["signedUrl"]

    def remove(self, name: str) -> None:
        self.client.storage.from_(self._bucket).remove([name])
