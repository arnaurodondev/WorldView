"""MinIO bronze-tier adapter for raw article storage.

Key pattern: ``content-ingestion/{source_type}/{url_hash}/raw/v1.json``

The adapter wraps ``libs/storage`` ``ObjectStorage`` and provides
domain-aware helpers that produce a JSON envelope containing both
metadata and the raw article bytes (base64-encoded).
"""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING, Any

import common.time
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from storage.interface import ObjectStorage

logger = get_logger(__name__)  # type: ignore[no-any-return]

_BUCKET = "worldview-bronze"


def build_bronze_key(source_type: str, url_hash: str) -> str:
    """Build the canonical MinIO key for a raw article."""
    return f"content-ingestion/{source_type}/{url_hash}/raw/v1.json"


class MinioBronzeAdapter:
    """Writes raw articles to MinIO bronze tier as JSON envelopes."""

    def __init__(self, storage: ObjectStorage, bucket: str = _BUCKET) -> None:
        self._storage = storage
        self._bucket = bucket

    async def put_object(
        self,
        source_type: str,
        url_hash: str,
        raw_bytes: bytes,
        *,
        url: str | None = None,
        fetched_at: str | None = None,
        published_at: str | None = None,
        is_backfill: bool = False,
    ) -> str:
        """Store a raw article and return the MinIO key.

        The stored object is a JSON envelope::

            {
                "url": "...",
                "source_type": "eodhd",
                "url_hash": "abc123...",
                "fetched_at": "2026-03-26T...",
                "published_at": "2026-03-25T..." | null,
                "is_backfill": false,
                "byte_size": 12345,
                "stored_at": "2026-03-26T...",
                "raw_b64": "<base64 encoded raw bytes>"
            }
        """
        key = build_bronze_key(source_type, url_hash)
        envelope: dict[str, Any] = {
            "url": url,
            "source_type": source_type,
            "url_hash": url_hash,
            "fetched_at": fetched_at or common.time.to_iso8601(common.time.utc_now()),
            "published_at": published_at,
            "is_backfill": is_backfill,
            "byte_size": len(raw_bytes),
            "stored_at": common.time.to_iso8601(common.time.utc_now()),
            "raw_b64": base64.b64encode(raw_bytes).decode("ascii"),
        }
        payload = json.dumps(envelope).encode("utf-8")
        await self._storage.put_bytes(self._bucket, key, payload, content_type="application/json")
        logger.debug("bronze_object_stored", key=key, byte_size=len(raw_bytes))
        return key

    async def object_exists(self, source_type: str, url_hash: str) -> bool:
        """Check if a bronze object already exists for this url_hash."""
        key = build_bronze_key(source_type, url_hash)
        return await self._storage.exists(self._bucket, key)
