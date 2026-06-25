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

# BUG #34 — prose fields, in priority order, used to recover the article body
# from a *raw* news envelope that leaked into storage as text.  content-ingestion
# emits source-specific JSON (EODHD: ``content``; NewsAPI: ``content``/
# ``description``; Yahoo/seed: ``summary``) and content-store's HTML cleaner ran
# bleach over that JSON string without finding any tags, so the silver ``body``
# ended up holding the *stringified raw JSON* rather than prose.  When we detect
# that shape we pull the longest available prose field here instead of handing
# the whole JSON to the sectioner (which would make chunk_index=0 the envelope).
_PROSE_FIELDS: tuple[str, ...] = ("body", "content", "summary", "description", "text")


def _recover_prose(text: str) -> str:
    """Return article prose, unwrapping a raw-news JSON envelope if ``text`` is one.

    The silver ``body`` *should* be cleaned prose, but for a large historical tail
    (BUG #34) it is the raw content-ingestion JSON re-encoded as a string —
    e.g. ``{"content": "<prose>", "date": ..., "symbols": [...]}`` (EODHD),
    ``{"summary": "<prose>", ...}`` (Yahoo/seed), or the NewsAPI shape.  Feeding
    that JSON straight to the sectioner corrupts chunk_index=0.

    Strategy:
    - If ``text`` does not parse as a JSON object, it is already prose → return as-is.
    - If it parses to a dict, take the first non-empty ``_PROSE_FIELDS`` value and
      recurse (the body itself may be doubly-encoded JSON).  This converges on the
      innermost prose string.
    - If a dict has none of the known prose fields, fall back to the original text
      so we never silently drop content for an unrecognised shape.
    """
    stripped = text.lstrip()
    # Cheap guard: only attempt a parse when it actually looks like a JSON object.
    if not stripped.startswith("{"):
        return text
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return text
    if not isinstance(parsed, dict):
        return text
    for field in _PROSE_FIELDS:
        value = parsed.get(field)
        if isinstance(value, str) and value.strip():
            # Recurse: an EODHD/NewsAPI ``content`` is prose, but the silver
            # ``body`` may wrap that envelope one extra time.
            return _recover_prose(value)
    # Recognised-as-JSON but no prose field — keep the original text rather than
    # dropping it; the sectioner's synthetic fallback still produces one section.
    return text


async def download_article(storage: Any, silver_bucket: str, minio_key: str) -> str:
    """Download cleaned article text from MinIO silver layer.

    The silver object is a JSON envelope (see content-store minio_silver.py):
    ``{"body": "<cleaned text>", "source_type": ..., ...}``

    S-006: Validate the key against the canonical silver-key pattern before
    attempting the download.  A non-canonical key means the upstream event was
    malformed or tampered — reject immediately so the error is visible rather
    than producing a confusing storage 404 or returning garbled content.

    BUG #34: ``envelope["body"]`` is *meant* to be cleaned prose, but for a large
    historical tail it holds the raw content-ingestion JSON re-encoded as a string
    (content-store's HTML cleaner left the JSON intact).  ``_recover_prose`` peels
    that off so chunk_index=0 becomes article text, never the JSON envelope.  We
    apply the same recovery to the non-envelope fall-through path so a bare raw
    JSON payload (no top-level ``body``) is handled identically.
    """
    if not KeyBuilder.is_valid_silver_key(minio_key):
        raise ValueError(f"Rejected non-canonical minio_key: {minio_key!r}")
    if storage is None:
        msg = "Object storage not configured; cannot download article text"
        raise RuntimeError(msg)
    raw = await storage.get_bytes(silver_bucket, minio_key)
    decoded = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    try:
        envelope = json.loads(decoded)
        if isinstance(envelope, dict) and "body" in envelope:
            return _recover_prose(str(envelope["body"]))
    except (json.JSONDecodeError, ValueError):
        pass
    # Non-``body`` payloads: could still be a raw news envelope (no top-level
    # ``body`` key) — recover prose rather than dumping the whole JSON as text.
    return _recover_prose(decoded)


async def extract_title_from_silver(storage: Any, silver_bucket: str, minio_key: str) -> str | None:
    """Best-effort: recover the article title from the silver JSON envelope.

    BUG #35: ``sec_edgar`` and ``newsapi`` Kafka events carry no ``title`` field,
    so ``doc_title`` is ``None`` and ``chunks.title_denorm`` lands NULL — which
    starves the learned router (it scores title-less docs near-floor and routes
    them to LIGHT, suppressing deep extraction).  The title IS recoverable from
    the silver object for NewsAPI: the envelope's top-level ``title`` is usually
    absent, but the raw-news JSON re-encoded into ``body`` (see BUG #34) carries
    an inner ``title``.  We probe both levels and return the first non-empty one.

    Returns ``None`` on any error or when no title is present (e.g. genuine
    sec_edgar filings expose no headline anywhere in silver) — the caller keeps
    its existing C-8 title-less fallback for that case.
    """
    if storage is None:
        return None
    try:
        raw = await storage.get_bytes(silver_bucket, minio_key)
        decoded = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        envelope = json.loads(decoded)
        if not isinstance(envelope, dict):
            return None
        # 1. Envelope-level title (populated for most eodhd docs).
        top_title = envelope.get("title")
        if isinstance(top_title, str) and top_title.strip():
            return top_title.strip()
        # 2. Inner raw-news JSON (NewsAPI/EODHD) re-encoded into ``body``.
        body = envelope.get("body")
        if isinstance(body, str) and body.lstrip().startswith("{"):
            inner = json.loads(body)
            if isinstance(inner, dict):
                inner_title = inner.get("title")
                if isinstance(inner_title, str) and inner_title.strip():
                    return inner_title.strip()
    except Exception:
        # Best-effort recovery only — a title-less doc keeps its C-8 fallback.
        return None
    return None


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
