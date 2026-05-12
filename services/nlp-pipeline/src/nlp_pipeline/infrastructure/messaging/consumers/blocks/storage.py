"""MinIO and source-metadata helpers for the article consumer.

Contains:
- ``download_article``      — download and unpack the silver-layer JSON envelope.
- ``extract_url_from_silver`` — best-effort URL extraction from the envelope.
- ``write_source_metadata`` — upsert citation metadata to nlp_db (best-effort).

All functions are pure I/O helpers that were previously private methods on
``ArticleProcessingConsumer``.  Extracting them here keeps the consumer class
focused on orchestration while allowing independent unit testing of the I/O
layer.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

import common.time  # type: ignore[import-untyped]
from nlp_pipeline.infrastructure.nlp_db.repositories.document_source_metadata import (
    SQLAlchemyDocumentSourceMetadataRepository,
)
from observability import get_logger  # type: ignore[import-untyped]
from storage.key_builder import KeyBuilder  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def download_article(storage: Any, silver_bucket: str, minio_key: str) -> str:
    """Download cleaned article text from MinIO silver layer.

    The silver object is a JSON envelope (see content-store minio_silver.py):
    ``{"body": "<cleaned text>", "source_type": ..., ...}``

    S-006: Validate the key against the canonical silver-key pattern before
    attempting the download.  A non-canonical key means the upstream event was
    malformed or tampered — reject immediately so the error is visible rather
    than producing a confusing storage 404 or returning garbled content.
    """
    if not KeyBuilder.is_valid_silver_key(minio_key):
        raise ValueError(f"Rejected non-canonical minio_key: {minio_key!r}")
    if storage is None:
        msg = "Object storage not configured; cannot download article text"
        raise RuntimeError(msg)
    raw = await storage.get_bytes(silver_bucket, minio_key)
    try:
        envelope = json.loads(raw)
        if isinstance(envelope, dict) and "body" in envelope:
            return str(envelope["body"])
    except (json.JSONDecodeError, ValueError):
        pass
    return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)


async def extract_url_from_silver(storage: Any, silver_bucket: str, minio_key: str) -> str | None:
    """Best-effort: extract source_url from the silver JSON envelope.

    Falls back to ``None`` on any error — the consumer uses this only for
    best-effort citation metadata caching and must never fail because of it.
    """
    if storage is None:
        return None
    try:
        raw = await storage.get_bytes(silver_bucket, minio_key)
        envelope = json.loads(raw)
        if isinstance(envelope, dict):
            return envelope.get("source_url") or None
    except Exception:
        return None
    return None


async def write_source_metadata(
    *,
    nlp_session_factory: async_sessionmaker[AsyncSession],
    doc_id: uuid.UUID,
    title: str | None,
    url: str | None,
    published_at: datetime | None,
    source_name: str | None,
    source_type: str | None,
    word_count: int | None,
) -> None:
    """Write citation metadata to nlp_db.document_source_metadata (best-effort).

    Any exception is logged as a warning and swallowed so that NLP processing
    is never blocked by a metadata write failure.
    """
    from nlp_pipeline.domain.models import DocumentSourceMetadata

    try:
        metadata = DocumentSourceMetadata(
            doc_id=doc_id,
            title=str(title) if title is not None else None,
            url=str(url) if url is not None else None,
            published_at=published_at,
            source_name=str(source_name) if source_name is not None else None,
            source_type=str(source_type) if source_type is not None else None,
            word_count=int(word_count) if word_count is not None else None,
            created_at=common.time.utc_now(),
        )
        async with nlp_session_factory() as session:
            repo = SQLAlchemyDocumentSourceMetadataRepository(session)
            await repo.upsert(metadata)
            await session.commit()
    except Exception:
        logger.warning("source_metadata_write_failed", doc_id=str(doc_id), exc_info=True)  # type: ignore[no-any-return]
