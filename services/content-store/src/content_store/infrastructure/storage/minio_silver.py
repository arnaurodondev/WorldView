"""MinIO silver-tier adapter for canonical document storage.

Writes cleaned, deduplicated article text to the silver bucket with
structured JSON envelopes containing metadata + cleaned text.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import structlog

import common.time  # type: ignore[import-untyped]
from content_store.application.ports.storage import SilverStoragePort

if TYPE_CHECKING:
    from content_store.domain.entities import CanonicalDocument
    from storage.interface import ObjectStorage

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Key pattern: content-store/canonical/{doc_id}/body.json
_KEY_PREFIX = "content-store/canonical"


def silver_key(doc_id: str) -> str:
    """Build the MinIO object key for a canonical document.

    Args:
        doc_id: String representation of the document UUID.

    Returns:
        MinIO key: ``content-store/canonical/{doc_id}/body.json``
    """
    return f"{_KEY_PREFIX}/{doc_id}/body.json"


async def put_canonical(
    store: ObjectStorage,
    bucket: str,
    doc: CanonicalDocument,
    cleaned_text: str,
) -> str:
    """Write a canonical document's cleaned text to MinIO silver tier.

    The JSON envelope includes metadata (source_type, title, published_at,
    word_count, content_hash) alongside the cleaned text body.

    Args:
        store: Object storage adapter (``libs/storage``).
        bucket: Silver bucket name.
        doc: The canonical document entity.
        cleaned_text: Cleaned, normalized article text.

    Returns:
        The MinIO object key that was written.
    """
    key = silver_key(str(doc.id))

    payload = {
        "doc_id": str(doc.id),
        "source_type": doc.source_type,
        "title": doc.title,
        "source_url": doc.source_url,
        "published_at": doc.published_at.isoformat() if doc.published_at else None,
        "content_hash": doc.content_hash,
        "normalized_hash": doc.normalized_hash,
        "word_count": doc.word_count,
        "language": doc.language,
        "stored_at": common.time.utc_now().isoformat(),
        "body": cleaned_text,
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    await store.put_bytes(bucket, key, data, content_type="application/json")

    logger.info(
        "silver_object_written",
        doc_id=str(doc.id),
        key=key,
        byte_size=len(data),
    )
    return key


class SilverStorageAdapter(SilverStoragePort):
    """Infrastructure adapter — wraps ``put_canonical`` behind ``SilverStoragePort``.

    Accepts a generic ObjectStorage and bucket name at construction time so the
    application layer never sees MinIO-specific configuration.
    """

    def __init__(self, store: ObjectStorage, silver_bucket: str) -> None:
        self._store = store
        self._silver_bucket = silver_bucket

    async def put_canonical(self, doc: CanonicalDocument, cleaned_text: str) -> str:
        return await put_canonical(self._store, self._silver_bucket, doc, cleaned_text)
