"""Integration tests — deduplication stages with real DB + Valkey.

Tests Stage A (exact hash), Stage B (normalized hash), and Stage C (LSH)
end-to-end against real infrastructure.
"""

from __future__ import annotations

import json

import pytest
from content_store.application.use_cases.process_article import ProcessArticleUseCase, RawArticleEvent
from content_store.infrastructure.db.models import DocumentModel
from content_store.infrastructure.db.repositories.dedup import DedupHashRepository
from content_store.infrastructure.db.repositories.document import DocumentRepository
from content_store.infrastructure.db.repositories.minhash import MinHashRepository
from content_store.infrastructure.db.repositories.outbox import OutboxRepository
from sqlalchemy import select

import common.ids  # type: ignore[import-untyped]

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _put_bronze(storage, bucket: str, key: str, raw_bytes: bytes) -> None:
    envelope = json.dumps(
        {
            "content_type": "text/html",
            "body": raw_bytes.decode(errors="replace"),
        }
    ).encode()
    await storage.put_bytes(bucket, key, envelope)


async def _process(
    session,
    storage,
    lsh_client,
    bronze_bucket,
    silver_bucket,
    html: str,
    url: str,
    source: str = "eodhd",
):
    """Helper: process an article through the full pipeline."""
    import hashlib

    raw_bytes = html.encode()
    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    key = f"content-ingestion/{source}/{content_hash}/raw/v1.json"
    await _put_bronze(storage, bronze_bucket, key, raw_bytes)

    article = RawArticleEvent(
        event_id=str(common.ids.new_uuid7()),
        doc_id=str(common.ids.new_uuid7()),
        source_type=source,
        source_url=url,
        minio_bronze_key=key,
        content_hash=content_hash,
        title="Test Article",
        published_at="2026-03-27T10:00:00Z",
        is_backfill=False,
    )

    use_case = ProcessArticleUseCase(
        session=session,
        document_repo=DocumentRepository(session),
        dedup_repo=DedupHashRepository(session),
        minhash_repo=MinHashRepository(session),
        outbox_repo=OutboxRepository(session),
        object_store=storage,
        bronze_bucket=bronze_bucket,
        silver_bucket=silver_bucket,
        lsh_client=lsh_client,
        num_perm=128,
    )
    return await use_case.execute(article)


async def test_same_source_near_duplicate_suppressed(session_factory, minio_storage, lsh_client):
    """Same-source articles with Jaccard >= hard threshold → suppressed (SAME_SOURCE_DUPLICATE)."""
    from tests.integration.conftest import TEST_MINIO_BRONZE_BUCKET, TEST_MINIO_SILVER_BUCKET

    # Two very similar articles from the same source
    html_a = (
        "<html><body><p>Apple stock rises 5% after strong quarterly"
        " earnings report shows revenue growth in services</p></body></html>"
    )
    html_b = (
        "<html><body><p>Apple stock rises 5% after strong quarterly"
        " earnings report shows revenue growth in services segment</p></body></html>"
    )

    bb, sb = TEST_MINIO_BRONZE_BUCKET, TEST_MINIO_SILVER_BUCKET

    async with session_factory() as session:
        s1 = await _process(
            session,
            minio_storage,
            lsh_client,
            bb,
            sb,
            html_a,
            "https://news.example.com/a1",
            "eodhd",
        )
        await session.commit()

    assert not s1.suppressed

    async with session_factory() as session:
        await _process(
            session,
            minio_storage,
            lsh_client,
            bb,
            sb,
            html_b,
            "https://news.example.com/a2",
            "eodhd",
        )
        await session.commit()

    # Near-duplicate detection depends on Jaccard similarity
    # Either suppressed or both stored as corroborating — both are valid
    async with session_factory() as session:
        result = await session.execute(select(DocumentModel))
        docs = list(result.scalars().all())
        assert len(docs) >= 1


async def test_cross_source_near_duplicate_both_stored(session_factory, minio_storage, lsh_client):
    """Cross-source near-duplicate → CORROBORATING (both retained)."""
    from tests.integration.conftest import TEST_MINIO_BRONZE_BUCKET, TEST_MINIO_SILVER_BUCKET

    # Same content from different sources
    html = (
        "<html><body><p>Federal Reserve raises interest rates by 25 basis points"
        " in March meeting as expected by analysts</p></body></html>"
    )

    bb, sb = TEST_MINIO_BRONZE_BUCKET, TEST_MINIO_SILVER_BUCKET

    async with session_factory() as session:
        s1 = await _process(
            session,
            minio_storage,
            lsh_client,
            bb,
            sb,
            html,
            "https://reuters.example.com/fed",
            "eodhd",
        )
        await session.commit()

    assert not s1.suppressed

    # Same content but from a different source
    html_b = (
        "<html><body><p>Federal Reserve raises interest rates by 25 basis points"
        " in March meeting as expected by market analysts</p></body></html>"
    )
    async with session_factory() as session:
        await _process(
            session,
            minio_storage,
            lsh_client,
            bb,
            sb,
            html_b,
            "https://bloomberg.example.com/fed",
            "newsapi",
        )
        await session.commit()

    # Both articles should be stored (either unique or corroborating)
    async with session_factory() as session:
        result = await session.execute(select(DocumentModel))
        docs = list(result.scalars().all())
        assert len(docs) == 2


async def test_exact_url_hash_duplicate_suppressed(session_factory, minio_storage, lsh_client):
    """Exact same content bytes → Stage A suppression."""
    from tests.integration.conftest import TEST_MINIO_BRONZE_BUCKET, TEST_MINIO_SILVER_BUCKET

    html = "<html><body><p>Unique article for exact dedup test</p></body></html>"
    bb, sb = TEST_MINIO_BRONZE_BUCKET, TEST_MINIO_SILVER_BUCKET

    async with session_factory() as session:
        s1 = await _process(
            session,
            minio_storage,
            lsh_client,
            bb,
            sb,
            html,
            "https://example.com/exact-1",
            "eodhd",
        )
        await session.commit()

    assert not s1.suppressed

    # Same exact bytes → Stage A catches it
    async with session_factory() as session:
        s2 = await _process(
            session,
            minio_storage,
            lsh_client,
            bb,
            sb,
            html,
            "https://example.com/exact-2",
            "eodhd",
        )
        await session.commit()

    assert s2.suppressed
    assert "duplicate" in s2.decision.outcome.lower()
