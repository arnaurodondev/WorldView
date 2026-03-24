"""S3ObjectStoreAdapter — wraps libs/storage.ObjectStorage.

Adapts the shared ``ObjectStorage`` ABC to the application-layer
``ObjectStoreAdapter`` port. SHA-256 is computed locally and embedded in the
returned ``ObjectRef`` for provenance tracking.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, cast

from market_ingestion.application.ports.adapters import ObjectStoreAdapter
from market_ingestion.domain.value_objects import ObjectRef
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from storage.interface import ObjectStorage  # type: ignore[import-untyped]

logger = get_logger(__name__)


class S3ObjectStoreAdapter(ObjectStoreAdapter):
    """Object storage adapter backed by ``libs/storage.ObjectStorage``.

    All four ``ObjectStoreAdapter`` methods delegate to the shared library
    and use the library's bucket-per-call API (``put_bytes(bucket, key, ...)``).
    SHA-256 is computed from the data bytes before upload and embedded in the
    returned ``ObjectRef``.
    """

    def __init__(self, storage: ObjectStorage, default_bucket: str = "market-ingestion") -> None:
        self._storage = storage
        self._default_bucket = default_bucket

    async def put(
        self,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> ObjectRef:
        """Upload *data* under *key* in *bucket* and return an ``ObjectRef``.

        SHA-256 is computed locally. The storage library handles the actual
        upload; no ETag is retrieved from the server.
        """
        sha256 = hashlib.sha256(data).hexdigest()
        byte_length = len(data)

        await self._storage.put_bytes(bucket, key, data, content_type)

        logger.debug(
            "object_stored",
            bucket=bucket,
            key=key,
            size=byte_length,
            sha256_prefix=sha256[:8],
        )

        return ObjectRef(
            bucket=bucket,
            key=key,
            sha256=sha256,
            byte_length=byte_length,
            mime_type=content_type,
        )

    async def get(self, bucket: str, key: str) -> bytes:
        """Retrieve raw bytes for *key* in *bucket*."""
        return cast("bytes", await self._storage.get_bytes(bucket, key))

    async def exists(self, bucket: str, key: str) -> bool:
        """Return True if *key* exists in *bucket*."""
        return cast("bool", await self._storage.exists(bucket, key))

    async def ensure_bucket(self, bucket: str) -> None:
        """No-op: bucket lifecycle is managed externally (infra init scripts)."""
