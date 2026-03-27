"""Storage port interfaces for the Content Store application layer."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from content_store.domain.entities import CanonicalDocument


class SilverStoragePort(ABC):
    """Port for writing canonical documents to the MinIO silver tier."""

    @abstractmethod
    async def put_canonical(self, doc: CanonicalDocument, cleaned_text: str) -> str:
        """Write a canonical document to MinIO silver and return the object key."""
