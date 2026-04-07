"""Storage port interfaces for the Content Store application layer."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from content_store.domain.entities import CanonicalDocument


class BronzeStoragePort(ABC):
    """Port for reading raw article bytes from the MinIO bronze tier (S4 writes, S5 reads).

    R24 compliance: callers MUST close any open DB session before calling
    ``get_bytes`` to avoid holding a connection during external I/O.
    """

    @abstractmethod
    async def get_bytes(self, bucket: str, key: str) -> bytes:
        """Fetch raw bytes for *key* from *bucket*.

        Raises
        ------
        OSError
            When the object does not exist or MinIO is unreachable.
        """


class SilverStoragePort(ABC):
    """Port for writing canonical documents to the MinIO silver tier."""

    @abstractmethod
    async def put_canonical(self, doc: CanonicalDocument, cleaned_text: str) -> str:
        """Write a canonical document to MinIO silver and return the object key."""
