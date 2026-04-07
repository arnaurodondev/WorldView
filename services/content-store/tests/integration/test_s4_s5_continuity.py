"""Integration tests — S4→S5 continuity.

Validates the contract between S4 (content-ingestion) and S5 (content-store):
S4 produces content.article.raw.v1 → bronze MinIO object + outbox event
S5 consumes → clean → dedup → canonical doc → silver MinIO + outbox event

This test simulates the S4 output format and verifies S5 can consume it end-to-end.
"""

from __future__ import annotations

import json

import pytest
from content_store.application.use_cases.process_article import ProcessArticleUseCase, RawArticleEvent
from content_store.infrastructure.db.models import DocumentModel, MinHashSignatureModel, OutboxEventModel
from content_store.infrastructure.db.repositories.dedup import DedupHashRepository
from content_store.infrastructure.db.repositories.document import DocumentRepository
from content_store.infrastructure.db.repositories.minhash import MinHashRepository
from content_store.infrastructure.db.repositories.outbox import OutboxRepository
from content_store.infrastructure.storage.minio_silver import SilverStorageAdapter
from sqlalchemy import select

import common.ids  # type: ignore[import-untyped]
import common.time  # type: ignore[import-untyped]

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _build_s4_raw_event(
    *,
    source_type: str = "eodhd",
    url: str = "https://eodhistoricaldata.com/news/12345",
    title: str = "AAPL Earnings Beat Expectations",
    html_body: str = (
        "<html><body><article><h1>AAPL Earnings Beat</h1>"
        "<p>Apple reported Q1 earnings above analyst expectations with revenue of $123B.</p>"
        "</article></body></html>"
    ),
) -> dict:
    """Build a content.article.raw.v1 Avro-like dict as S4 would produce.

    This matches the schema fields from infra/kafka/schemas/content.article.raw.v1.avsc.
    """
    import hashlib

    raw_bytes = html_body.encode()
    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    doc_id = str(common.ids.new_uuid7())
    minio_key = f"content-ingestion/{source_type}/{content_hash}/raw/v1.json"

    return {
        "event_id": str(common.ids.new_uuid7()),
        "event_type": "content.article.raw",
        "schema_version": 1,
        "occurred_at": common.time.utc_now().isoformat(),
        "doc_id": doc_id,
        "source_type": source_type,
        "source_url": url,
        "url_hash": hashlib.sha256(url.encode()).hexdigest(),
        "minio_bronze_key": minio_key,
        "content_hash": content_hash,
        "title": title,
        "fetched_at": common.time.utc_now().isoformat(),
        "byte_size": len(raw_bytes),
        "published_at": "2026-03-27T08:00:00Z",
        "is_backfill": False,
        # For test: embed the raw bytes for MinIO seeding
        "_raw_bytes": raw_bytes,
    }


async def test_s4_to_s5_full_pipeline(session_factory, minio_storage, lsh_client):
    """End-to-end: S4 raw event → S5 consumer → canonical doc → silver + outbox.

    Validates the full contract between the two services.
    """
    from tests.integration.conftest import TEST_MINIO_BRONZE_BUCKET, TEST_MINIO_SILVER_BUCKET

    # 1. Simulate S4 output: write raw article to MinIO bronze
    raw_event = _build_s4_raw_event()
    raw_bytes = raw_event.pop("_raw_bytes")

    # S4 writes a JSON envelope to bronze
    bronze_envelope = json.dumps(
        {
            "content_type": "text/html",
            "body": raw_bytes.decode(),
            "metadata": {
                "source_type": raw_event["source_type"],
                "url": raw_event["source_url"],
                "fetched_at": raw_event["fetched_at"],
            },
        }
    ).encode()
    await minio_storage.put_bytes(
        TEST_MINIO_BRONZE_BUCKET,
        raw_event["minio_bronze_key"],
        bronze_envelope,
    )

    # 2. S5 consumer receives the deserialized Avro event
    article = RawArticleEvent(
        event_id=raw_event["event_id"],
        doc_id=raw_event["doc_id"],
        source_type=raw_event["source_type"],
        source_url=raw_event["source_url"],
        minio_bronze_key=raw_event["minio_bronze_key"],
        content_hash=raw_event["content_hash"],
        title=raw_event["title"],
        published_at=raw_event["published_at"],
        is_backfill=raw_event["is_backfill"],
    )

    # 3. Process through the S5 pipeline
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
            output_topic="content.article.stored.v1",
            num_perm=128,
        )
        summary = await use_case.execute(article)
        await session.commit()

    # 4. Verify: not suppressed (first-time article)
    assert not summary.suppressed
    assert summary.doc_id is not None

    # 5. Verify: canonical document stored in DB
    async with session_factory() as session:
        result = await session.execute(select(DocumentModel).where(DocumentModel.doc_id == summary.doc_id))
        doc = result.scalar_one()
        assert doc.source_type == "eodhd"
        assert doc.title == "AAPL Earnings Beat Expectations"
        assert doc.content_hash == raw_event["content_hash"]
        assert doc.minio_silver_key is not None
        assert doc.status == "stored"
        assert doc.dedup_result == "unique"

    # 6. Verify: MinHash signature with INTEGER[] (regression guard)
    async with session_factory() as session:
        result = await session.execute(
            select(MinHashSignatureModel).where(MinHashSignatureModel.doc_id == summary.doc_id)
        )
        sig = result.scalar_one()
        assert isinstance(sig.signature, list)
        assert len(sig.signature) == 128
        assert all(isinstance(v, int) for v in sig.signature)

    # 7. Verify: outbox event for content.article.stored.v1
    async with session_factory() as session:
        result = await session.execute(
            select(OutboxEventModel).where(OutboxEventModel.event_type == "content.article.stored.v1")
        )
        outbox = result.scalar_one()
        assert outbox.status == "pending"
        assert outbox.aggregate_type == "document"
        payload = outbox.payload
        assert payload["doc_id"] == str(summary.doc_id)
        assert payload["source_type"] == "eodhd"
        assert payload["minio_silver_key"] == doc.minio_silver_key

    # 8. Verify: silver object in MinIO
    silver_data = await minio_storage.get_bytes(TEST_MINIO_SILVER_BUCKET, doc.minio_silver_key)
    silver_obj = json.loads(silver_data)
    assert "body" in silver_obj
    assert len(silver_obj["body"]) > 0


async def test_s4_backfill_flag_propagated(session_factory, minio_storage, lsh_client):
    """Verify that S4's is_backfill flag is preserved through S5."""
    from tests.integration.conftest import TEST_MINIO_BRONZE_BUCKET, TEST_MINIO_SILVER_BUCKET

    raw_event = _build_s4_raw_event(
        title="Historical SEC Filing",
        html_body="<html><body><p>Annual report filing from 2024 Q4 with detailed financials</p></body></html>",
        source_type="sec_edgar",
    )
    raw_bytes = raw_event.pop("_raw_bytes")

    envelope = json.dumps({"content_type": "text/html", "body": raw_bytes.decode()}).encode()
    await minio_storage.put_bytes(TEST_MINIO_BRONZE_BUCKET, raw_event["minio_bronze_key"], envelope)

    article = RawArticleEvent(
        event_id=raw_event["event_id"],
        doc_id=raw_event["doc_id"],
        source_type=raw_event["source_type"],
        source_url=raw_event["source_url"],
        minio_bronze_key=raw_event["minio_bronze_key"],
        content_hash=raw_event["content_hash"],
        title=raw_event["title"],
        published_at=None,
        is_backfill=True,
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

    async with session_factory() as session:
        result = await session.execute(select(DocumentModel).where(DocumentModel.doc_id == summary.doc_id))
        doc = result.scalar_one()
        assert doc.is_backfill is True

    # Verify outbox payload also has is_backfill
    async with session_factory() as session:
        result = await session.execute(select(OutboxEventModel))
        outbox = result.scalar_one()
        assert outbox.payload["is_backfill"] is True
