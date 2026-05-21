"""Abstract base class for object storage adapters."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from storage.buckets import BucketTier


class ObjectStorage(ABC):
    """Interface for S3-compatible object storage backends.

    All implementations must be fully async.  Use :func:`storage.factory.build_object_storage`
    to obtain a concrete instance rather than importing an adapter directly.

    Key format must always follow the canonical convention enforced by
    :class:`storage.key_builder.KeyBuilder`.
    """

    @abstractmethod
    async def put_bytes(
        self,
        bucket: str | BucketTier,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> None:
        """Upload raw bytes to *key* in *bucket*.

        Args:
            bucket: Target bucket name — accepts either a raw string or a
                :class:`~storage.buckets.BucketTier` enum member for type safety.
            key: Object key (canonical format).
            data: Raw bytes to upload.
            content_type: MIME content-type header value.
        """

    @abstractmethod
    async def get_bytes(self, bucket: str | BucketTier, key: str) -> bytes:
        """Download and return the raw bytes for *key* in *bucket*.

        Raises:
            :exc:`storage.exceptions.ObjectNotFoundError`: If the key does not exist.
            :exc:`storage.exceptions.BucketNotFoundError`: If the bucket does not exist.
        """

    @abstractmethod
    async def delete(self, bucket: str, key: str) -> None:
        """Delete *key* from *bucket*.

        This is a no-op if the key does not exist (S3 delete semantics).
        """

    @abstractmethod
    async def list_keys(self, bucket: str, prefix: str = "") -> list[str]:
        """Return all object keys in *bucket* that start with *prefix*.

        Args:
            bucket: Bucket to list.
            prefix: Optional key prefix filter (empty = all keys).

        Returns:
            Sorted list of matching key strings.
        """

    @abstractmethod
    async def exists(self, bucket: str, key: str) -> bool:
        """Return ``True`` if *key* exists in *bucket*, ``False`` otherwise."""

    @abstractmethod
    async def delete_prefix(self, bucket: str, prefix: str) -> int:
        """Delete all objects whose key starts with *prefix* in *bucket*.

        Args:
            bucket: Bucket to operate on.
            prefix: Key prefix to match.

        Returns:
            Number of objects deleted.
        """

    # ------------------------------------------------------------------ helpers

    async def put_json(
        self,
        bucket: str,
        key: str,
        data: dict[str, Any],
    ) -> None:
        """Serialise *data* as UTF-8 JSON and upload to *key* in *bucket*."""
        payload = json.dumps(data, ensure_ascii=False).encode()
        await self.put_bytes(bucket, key, payload, content_type="application/json")

    async def get_json(self, bucket: str, key: str) -> dict[str, Any]:
        """Download *key* from *bucket* and deserialise as JSON.

        Returns:
            Parsed JSON object.

        Raises:
            :exc:`storage.exceptions.ObjectNotFoundError`: If the key does not exist.
            :exc:`json.JSONDecodeError`: If the stored bytes are not valid JSON.
        """
        raw = await self.get_bytes(bucket, key)
        result: dict[str, Any] = json.loads(raw.decode())
        return result
