"""Integration tests — idempotency of the S5 consumer pipeline.

Validates that processing the same Kafka message twice produces exactly one canonical document.
"""

from __future__ import annotations

import json

import pytest
from content_store.application.use_cases.process_article import ProcessArticleUseCase, RawArticleEvent
from content_store.infrastructure.db.models import DocumentModel, OutboxEventModel
from content_store.infrastructure.db.repositories.dedup import DedupHashRepository
from content_store.infrastructure.db.repositories.document import DocumentRepository
from content_store.infrastructure.db.repositories.minhash import MinHashRepository
from content_store.infrastructure.db.repositories.outbox import OutboxRepository
from content_store.infrastructure.storage.minio_bronze import BronzeStorageAdapter
from content_store.infrastructure.storage.minio_silver import SilverStorageAdapter
from sqlalchemy import func, select

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


async def test_same_message_twice_produces_single_document(session_factory, minio_storage, lsh_client):
    """Simulates Kafka at-least-once: same raw event processed twice → 1 doc, 1 outbox."""
    import hashlib

    from tests.integration.conftest import TEST_MINIO_BRONZE_BUCKET, TEST_MINIO_SILVER_BUCKET

    html = "<html><body><p>Idempotency test article with unique content for dedup verification</p></body></html>"
    raw_bytes = html.encode()
    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    key = f"content-ingestion/eodhd/{content_hash}/raw/v1.json"
    await _put_bronze(minio_storage, TEST_MINIO_BRONZE_BUCKET, key, raw_bytes)

    event_id = str(common.ids.new_uuid7())
    doc_id = str(common.ids.new_uuid7())

    article = RawArticleEvent(
        event_id=event_id,
        doc_id=doc_id,
        source_type="eodhd",
        source_url="https://example.com/idempotency-test",
        minio_bronze_key=key,
        content_hash=content_hash,
        title="Idempotency Test",
        published_at="2026-03-27T12:00:00Z",
        is_backfill=False,
    )

    # First processing — should succeed
    async with session_factory() as session:
        use_case = ProcessArticleUseCase(
            document_repo=DocumentRepository(session),
            dedup_repo=DedupHashRepository(session),
            minhash_repo=MinHashRepository(session),
            outbox_repo=OutboxRepository(session),
            bronze_store=BronzeStorageAdapter(minio_storage, TEST_MINIO_BRONZE_BUCKET),
            bronze_bucket=TEST_MINIO_BRONZE_BUCKET,
            silver_storage=SilverStorageAdapter(minio_storage, TEST_MINIO_SILVER_BUCKET),
            lsh_client=lsh_client,
            num_perm=128,
        )
        summary1 = await use_case.execute(article)
        await session.commit()

    assert not summary1.suppressed

    # Second processing — same bytes → Stage A dedup catches it
    async with session_factory() as session:
        use_case = ProcessArticleUseCase(
            document_repo=DocumentRepository(session),
            dedup_repo=DedupHashRepository(session),
            minhash_repo=MinHashRepository(session),
            outbox_repo=OutboxRepository(session),
            bronze_store=BronzeStorageAdapter(minio_storage, TEST_MINIO_BRONZE_BUCKET),
            bronze_bucket=TEST_MINIO_BRONZE_BUCKET,
            silver_storage=SilverStorageAdapter(minio_storage, TEST_MINIO_SILVER_BUCKET),
            lsh_client=lsh_client,
            num_perm=128,
        )
        summary2 = await use_case.execute(article)
        await session.commit()

    assert summary2.suppressed

    # Verify exactly 1 document and 1 outbox event
    async with session_factory() as session:
        doc_count = await session.execute(select(func.count()).select_from(DocumentModel))
        assert doc_count.scalar() == 1

        outbox_count = await session.execute(select(func.count()).select_from(OutboxEventModel))
        assert outbox_count.scalar() == 1


async def test_different_content_produces_separate_documents(session_factory, minio_storage, lsh_client):
    """Two distinct articles → two separate documents (not idempotent suppression)."""
    import hashlib

    from tests.integration.conftest import TEST_MINIO_BRONZE_BUCKET, TEST_MINIO_SILVER_BUCKET

    articles = [
        "<html><body><p>First unique article about cryptocurrency regulation in EU</p></body></html>",
        "<html><body><p>Second unique article about semiconductor supply chain in APAC</p></body></html>",
    ]
    for i, text in enumerate(articles):
        raw_bytes = text.encode()
        content_hash = hashlib.sha256(raw_bytes).hexdigest()
        key = f"content-ingestion/newsapi/{content_hash}/raw/v1.json"
        await _put_bronze(minio_storage, TEST_MINIO_BRONZE_BUCKET, key, raw_bytes)

        article = RawArticleEvent(
            event_id=str(common.ids.new_uuid7()),
            doc_id=str(common.ids.new_uuid7()),
            source_type="newsapi",
            source_url=f"https://example.com/article-{i}",
            minio_bronze_key=key,
            content_hash=content_hash,
            title=f"Article {i}",
            published_at="2026-03-27T12:00:00Z",
            is_backfill=False,
        )

        async with session_factory() as session:
            use_case = ProcessArticleUseCase(
                document_repo=DocumentRepository(session),
                dedup_repo=DedupHashRepository(session),
                minhash_repo=MinHashRepository(session),
                outbox_repo=OutboxRepository(session),
                object_store=minio_storage,
                bronze_bucket=TEST_MINIO_BRONZE_BUCKET,
                silver_storage=SilverStorageAdapter(minio_storage, TEST_MINIO_SILVER_BUCKET),
                lsh_client=lsh_client,
                num_perm=128,
            )
            summary = await use_case.execute(article)
            await session.commit()

        assert not summary.suppressed

    # Verify 2 documents and 2 outbox events
    async with session_factory() as session:
        doc_count = await session.execute(select(func.count()).select_from(DocumentModel))
        assert doc_count.scalar() == 2

        outbox_count = await session.execute(select(func.count()).select_from(OutboxEventModel))
        assert outbox_count.scalar() == 2
