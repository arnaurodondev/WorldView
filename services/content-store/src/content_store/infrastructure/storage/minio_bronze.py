"""MinIO bronze-tier adapter for reading raw article bytes (S4 writes, S5 reads).

Wraps ``libs/storage`` ``ObjectStorage`` and implements ``BronzeStoragePort``
so the application layer has no direct dependency on the storage library.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from content_store.application.ports.storage import BronzeStoragePort

if TYPE_CHECKING:
    from storage.interface import ObjectStorage  # type: ignore[import-untyped]


class BronzeStorageAdapter(BronzeStoragePort):
    """Implements BronzeStoragePort over an ``ObjectStorage`` (libs/storage)."""

    def __init__(self, store: ObjectStorage, bucket: str) -> None:
        self._store = store
        self._bucket = bucket

    async def get_bytes(self, bucket: str, key: str) -> bytes:
        """Fetch raw bytes from MinIO bronze bucket."""
        return await self._store.get_bytes(bucket, key)  # type: ignore[return-value]
