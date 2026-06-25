"""Integration tests — full S5 pipeline: bronze → clean → dedup → silver + outbox.

These tests exercise the real DB and MinIO but mock Kafka (no real consumer/producer).
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
from sqlalchemy import select

import common.ids  # type: ignore[import-untyped]

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


_DEFAULT_HTML = "<html><body><p>Test article content about markets</p></body></html>"


def _seed_bronze_article(raw_text: str = _DEFAULT_HTML) -> tuple[str, bytes, str]:
    """Return (minio_key, raw_bytes, content_hash)."""
    import hashlib

    raw_bytes = raw_text.encode()
    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    minio_key = f"content-ingestion/eodhd/{content_hash}/raw/v1.json"
    return minio_key, raw_bytes, content_hash


async def _put_bronze(minio_storage, bucket: str, key: str, raw_bytes: bytes) -> None:
    """Write a raw article to MinIO bronze bucket."""
    envelope = json.dumps(
        {
            "content_type": "text/html",
            "body": raw_bytes.decode(errors="replace"),
        }
    ).encode()
    await minio_storage.put_bytes(bucket, key, envelope)


async def _make_use_case(session, minio_storage, lsh_client, bronze_bucket: str, silver_bucket: str):
    """Build a ProcessArticleUseCase with real repos."""
    return ProcessArticleUseCase(
        document_repo=DocumentRepository(session),
        dedup_repo=DedupHashRepository(session),
        minhash_repo=MinHashRepository(session),
        outbox_repo=OutboxRepository(session),
        bronze_store=BronzeStorageAdapter(minio_storage, bronze_bucket),
        bronze_bucket=bronze_bucket,
        silver_storage=SilverStorageAdapter(minio_storage, silver_bucket),
        lsh_client=lsh_client,
        output_topic="content.article.stored.v1",
        num_perm=128,
    )


async def test_pipeline_stores_unique_article(session_factory, minio_storage, lsh_client):
    """Unique article → document row + dedup hashes + minhash + outbox + silver object."""
    from tests.integration.conftest import TEST_MINIO_BRONZE_BUCKET, TEST_MINIO_SILVER_BUCKET

    key, raw_bytes, content_hash = _seed_bronze_article(
        "<html><body><p>Breaking news: stock markets rally on earnings beat</p></body></html>"
    )
    await _put_bronze(minio_storage, TEST_MINIO_BRONZE_BUCKET, key, raw_bytes)

    article = RawArticleEvent(
        event_id=str(common.ids.new_uuid7()),
        doc_id=str(common.ids.new_uuid7()),
        source_type="eodhd",
        source_url="https://example.com/article-1",
        minio_bronze_key=key,
        content_hash=content_hash,
        title="Markets Rally",
        published_at="2026-03-27T10:00:00Z",
        is_backfill=False,
    )

    async with session_factory() as session:
        use_case = await _make_use_case(
            session,
            minio_storage,
            lsh_client,
            TEST_MINIO_BRONZE_BUCKET,
            TEST_MINIO_SILVER_BUCKET,
        )
        summary = await use_case.execute(article)
        await session.commit()

    assert not summary.suppressed
    assert summary.doc_id is not None

    # Verify document row
    async with session_factory() as session:
        result = await session.execute(select(DocumentModel))
        docs = list(result.scalars().all())
        assert len(docs) == 1
        assert docs[0].source_type == "eodhd"
        assert docs[0].title == "Markets Rally"
        assert docs[0].minio_silver_key is not None

    # Verify outbox event
    async with session_factory() as session:
        result = await session.execute(select(OutboxEventModel).where(OutboxEventModel.status == "pending"))
        outbox = list(result.scalars().all())
        assert len(outbox) == 1
        assert outbox[0].event_type == "content.article.stored.v1"

    # Verify silver object exists in MinIO
    silver_key = docs[0].minio_silver_key
    obj = await minio_storage.get_bytes(TEST_MINIO_SILVER_BUCKET, silver_key)
    assert len(obj) > 0


async def test_pipeline_suppresses_exact_duplicate(session_factory, minio_storage, lsh_client):
    """Same content hash submitted twice → second is suppressed (Stage A)."""
    from tests.integration.conftest import TEST_MINIO_BRONZE_BUCKET, TEST_MINIO_SILVER_BUCKET

    key, raw_bytes, content_hash = _seed_bronze_article(
        "<html><body><p>Duplicate article about interest rate hikes</p></body></html>"
    )
    await _put_bronze(minio_storage, TEST_MINIO_BRONZE_BUCKET, key, raw_bytes)

    def _make_article():
        return RawArticleEvent(
            event_id=str(common.ids.new_uuid7()),
            doc_id=str(common.ids.new_uuid7()),
            source_type="eodhd",
            source_url="https://example.com/dup-article",
            minio_bronze_key=key,
            content_hash=content_hash,
            title="Rate Hikes",
            published_at="2026-03-27T11:00:00Z",
            is_backfill=False,
        )

    # First submission — should succeed
    async with session_factory() as session:
        use_case = await _make_use_case(
            session,
            minio_storage,
            lsh_client,
            TEST_MINIO_BRONZE_BUCKET,
            TEST_MINIO_SILVER_BUCKET,
        )
        summary1 = await use_case.execute(_make_article())
        await session.commit()

    assert not summary1.suppressed

    # Second submission — same content hash → suppressed
    async with session_factory() as session:
        use_case = await _make_use_case(
            session,
            minio_storage,
            lsh_client,
            TEST_MINIO_BRONZE_BUCKET,
            TEST_MINIO_SILVER_BUCKET,
        )
        summary2 = await use_case.execute(_make_article())
        await session.commit()

    assert summary2.suppressed
    assert summary2.decision.outcome in ("duplicate_exact",)

    # Only 1 document row should exist
    async with session_factory() as session:
        result = await session.execute(select(DocumentModel))
        assert len(list(result.scalars().all())) == 1


async def test_pipeline_minhash_signature_stored_as_integer_list(session_factory, minio_storage, lsh_client):
    """Regression guard: minhash_signatures.signature is stored as INTEGER[], not BYTEA."""
    from content_store.infrastructure.db.models import MinHashSignatureModel

    from tests.integration.conftest import TEST_MINIO_BRONZE_BUCKET, TEST_MINIO_SILVER_BUCKET

    key, raw_bytes, content_hash = _seed_bronze_article(
        "<html><body><p>Financial results show growth in tech sector earnings</p></body></html>"
    )
    await _put_bronze(minio_storage, TEST_MINIO_BRONZE_BUCKET, key, raw_bytes)

    article = RawArticleEvent(
        event_id=str(common.ids.new_uuid7()),
        doc_id=str(common.ids.new_uuid7()),
        source_type="newsapi",
        source_url="https://example.com/tech-earnings",
        minio_bronze_key=key,
        content_hash=content_hash,
        title="Tech Earnings",
        published_at=None,
        is_backfill=False,
    )

    async with session_factory() as session:
        use_case = await _make_use_case(
            session,
            minio_storage,
            lsh_client,
            TEST_MINIO_BRONZE_BUCKET,
            TEST_MINIO_SILVER_BUCKET,
        )
        await use_case.execute(article)
        await session.commit()

    # Verify signature type
    async with session_factory() as session:
        result = await session.execute(select(MinHashSignatureModel))
        sigs = list(result.scalars().all())
        assert len(sigs) == 1
        sig = sigs[0].signature
        assert isinstance(sig, list)
        assert len(sig) == 128
        assert all(isinstance(v, int) for v in sig)
