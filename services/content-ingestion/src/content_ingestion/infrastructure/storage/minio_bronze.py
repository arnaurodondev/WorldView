"""MinIO bronze adapter — raw article storage under content-ingestion/ prefix."""

from __future__ import annotations

import asyncio
import io
from typing import TYPE_CHECKING, Any

import structlog

from content_ingestion.domain.exceptions import StorageError

if TYPE_CHECKING:
    from content_ingestion.config import Settings

logger = structlog.get_logger(__name__)


class MinioBronzeAdapter:
    """Wraps the synchronous MinIO client with asyncio.to_thread for async use.

    Key pattern: ``content-ingestion/{source_type}/{url_hash}/raw/v1.json``
    """

    def __init__(self, client: Any, settings: Settings) -> None:
        self._client = client
        self._bucket = settings.MINIO_BUCKET

    async def put_object(self, key: str, data: bytes, content_type: str = "application/json") -> None:
        """Upload *data* to MinIO at *key* inside the configured bucket."""
        try:
            await asyncio.to_thread(
                self._client.put_object,
                self._bucket,
                key,
                io.BytesIO(data),
                len(data),
                content_type=content_type,
            )
            logger.info("minio.put_object", bucket=self._bucket, key=key, size=len(data))
        except Exception as exc:
            raise StorageError(f"MinIO put_object failed for key={key!r}: {exc}") from exc

    async def object_exists(self, key: str) -> bool:
        """Return True if *key* exists in the configured bucket."""
        try:
            await asyncio.to_thread(self._client.stat_object, self._bucket, key)
            return True
        except Exception:
            return False
