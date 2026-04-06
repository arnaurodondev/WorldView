"""MinIO-backed chunk text store — infrastructure adapter for ChunkTextStorePort.

Stores chunk text as UTF-8 plaintext objects using the canonical key format:
    nlp-pipeline/chunk-text/{doc_id}/{chunk_id}/body/v1.txt

Reads are parallelised with ``asyncio.gather``; failures for individual
chunks are swallowed so one bad key never blocks the rest of the batch.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from nlp_pipeline.application.ports.repositories import ChunkTextStorePort
from observability import get_logger  # type: ignore[import-untyped]
from storage.key_builder import KeyBuilder  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from uuid import UUID

    from storage.interface import ObjectStorage  # type: ignore[import-untyped]

_log = get_logger(__name__)  # type: ignore[no-any-return]

_SERVICE = "nlp-pipeline"
_DOMAIN = "chunk-text"
_ARTIFACT = "body"
_VERSION = "v1"
_EXT = "txt"


def _build_key(doc_id: UUID, chunk_id: UUID) -> str:
    return KeyBuilder.build(
        service=_SERVICE,
        domain=_DOMAIN,
        resource_id=f"{doc_id}/{chunk_id}",
        artifact=_ARTIFACT,
        version=_VERSION,
        extension=_EXT,
    )


class MinIOChunkTextStore(ChunkTextStorePort):
    """Stores and retrieves chunk text from MinIO via ``libs/storage.ObjectStorage``."""

    def __init__(self, storage: ObjectStorage, bucket: str) -> None:
        self._storage = storage
        self._bucket = bucket

    async def put(self, chunk_id: UUID, doc_id: UUID, text: str) -> str:
        """Upload ``text`` to MinIO; return the canonical storage key."""
        key = _build_key(doc_id, chunk_id)
        data = text.encode("utf-8")
        await self._storage.put_bytes(self._bucket, key, data, content_type="text/plain; charset=utf-8")
        _log.debug(  # type: ignore[no-any-return]
            "chunk_text_uploaded",
            chunk_id=str(chunk_id),
            key=key,
            bytes=len(data),
        )
        return key

    async def get_batch(self, key_map: dict[UUID, str]) -> dict[UUID, str]:
        """Fetch texts for ``key_map`` in parallel; skip failed fetches."""
        if not key_map:
            return {}

        chunk_ids = list(key_map.keys())
        keys = [key_map[cid] for cid in chunk_ids]

        raw_results = await asyncio.gather(
            *[self._storage.get_bytes(self._bucket, key) for key in keys],
            return_exceptions=True,
        )

        out: dict[UUID, str] = {}
        for chunk_id, result in zip(chunk_ids, raw_results, strict=True):
            if isinstance(result, BaseException):
                _log.warning(  # type: ignore[no-any-return]
                    "chunk_text_fetch_failed",
                    chunk_id=str(chunk_id),
                    error=str(result),
                )
                continue
            out[chunk_id] = result.decode("utf-8", errors="replace")

        return out
