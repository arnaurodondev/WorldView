"""Integration tests for the S4 fetch-and-write pipeline (T-A-4-03).

Validates: mock adapter → FetchAndWriteUseCase → MinIO bronze + fetch_log + outbox_event.

Requires live PostgreSQL and MinIO.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from content_ingestion.application.use_cases.fetch_and_write import FetchAndWriteUseCase, FetchSummary
from content_ingestion.domain.entities import FetchResult, Source, SourceType
from content_ingestion.infrastructure.db.models import FetchLogModel, OutboxEventModel
from content_ingestion.infrastructure.db.repositories.fetch_log import FetchLogRepository
from content_ingestion.infrastructure.db.repositories.outbox import OutboxRepository
from content_ingestion.infrastructure.db.repositories.source import SourceRepository
from content_ingestion.infrastructure.storage.minio_bronze import MinioBronzeAdapter, build_bronze_key
from sqlalchemy import func, select

import common.time

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("S4_TEST_DATABASE_URL", "postgresql").startswith("postgresql"),
        reason="Requires live PostgreSQL (set S4_TEST_DATABASE_URL)",
    ),
]

# ── Helpers ──────────────────────────────────────────────────────────────────


async def _seed_source(session_factory, name="test-eodhd", source_type="eodhd") -> Source:
    """Insert a source into the DB and return a domain Source with the DB-generated ID."""
    async with session_factory() as session:
        repo = SourceRepository(session)
        model = await repo.create(name=name, source_type=source_type, config={}, enabled=True)
        await session.commit()
        return Source(
            id=model.id,
            name=model.name,
            source_type=SourceType(model.source_type),
            enabled=model.enabled,
            config=model.config,
            created_at=model.created_at,
        )


def _make_fetch_result(source_id, url="https://example.com/article-1", url_hash="abc123"):
    return FetchResult(
        source_id=source_id,
        url=url,
        url_hash=url_hash,
        raw_bytes=b'{"title": "Test Article", "body": "Content here"}',
        fetched_at=common.time.utc_now(),
        http_status=200,
        content_type="application/json",
        published_at=datetime(2026, 3, 25, 12, 0, 0, tzinfo=UTC),
        is_backfill=False,
    )


# ── Pipeline tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pipeline_creates_fetch_log_and_outbox(session_factory):
    """FetchAndWriteUseCase creates a fetch_log row and an outbox event in one transaction."""
    source = await _seed_source(session_factory)
    result = _make_fetch_result(source.id)

    mock_adapter = AsyncMock()
    mock_adapter.fetch = AsyncMock(return_value=[result])
    mock_bronze = AsyncMock(spec=MinioBronzeAdapter)
    mock_bronze.put_object = AsyncMock(return_value=build_bronze_key("eodhd", result.url_hash))

    async with session_factory() as session:
        use_case = FetchAndWriteUseCase(
            adapter=mock_adapter,
            bronze=mock_bronze,
            fetch_log_repo=FetchLogRepository(session),
            outbox_repo=OutboxRepository(session),
            commit_fn=session.commit,
        )
        summary = await use_case.execute(source, is_backfill=False)

    assert isinstance(summary, FetchSummary)
    assert summary.fetched == 1
    assert summary.skipped == 0
    assert summary.failed == 0

    # Verify fetch_log row
    async with session_factory() as session:
        log_result = await session.execute(select(func.count()).select_from(FetchLogModel))
        assert log_result.scalar() == 1

        log_row = (await session.execute(select(FetchLogModel))).scalar_one()
        assert log_row.url_hash == result.url_hash
        assert log_row.url == result.url
        assert log_row.source_id == source.id

    # Verify outbox event
    async with session_factory() as session:
        outbox_result = await session.execute(select(func.count()).select_from(OutboxEventModel))
        assert outbox_result.scalar() == 1

        outbox_row = (await session.execute(select(OutboxEventModel))).scalar_one()
        assert outbox_row.event_type == "content.article.raw.v1"
        assert outbox_row.status == "pending"
        assert outbox_row.payload["url_hash"] == result.url_hash
        assert outbox_row.payload["source_type"] == "eodhd"


@pytest.mark.asyncio
async def test_pipeline_with_real_minio(session_factory, minio_storage):
    """Full pipeline: adapter → MinIO bronze write → fetch_log + outbox."""
    source = await _seed_source(session_factory, name="test-minio-pipeline")
    result = _make_fetch_result(source.id, url="https://example.com/minio-test", url_hash="minio_hash_001")

    mock_adapter = AsyncMock()
    mock_adapter.fetch = AsyncMock(return_value=[result])

    from tests.integration.conftest import TEST_MINIO_BUCKET

    bronze = MinioBronzeAdapter(minio_storage, bucket=TEST_MINIO_BUCKET)

    async with session_factory() as session:
        use_case = FetchAndWriteUseCase(
            adapter=mock_adapter,
            bronze=bronze,
            fetch_log_repo=FetchLogRepository(session),
            outbox_repo=OutboxRepository(session),
            commit_fn=session.commit,
        )
        summary = await use_case.execute(source, is_backfill=False)

    assert summary.fetched == 1

    # Verify MinIO object exists
    expected_key = build_bronze_key("eodhd", "minio_hash_001")
    exists = await bronze.object_exists("eodhd", "minio_hash_001")
    assert exists, f"Expected MinIO object at key: {expected_key}"


@pytest.mark.asyncio
async def test_pipeline_adapter_failure_returns_summary_with_error(session_factory):
    """When the adapter raises, the use-case returns a failed summary (not exception)."""
    source = await _seed_source(session_factory, name="test-adapter-fail")

    mock_adapter = AsyncMock()
    mock_adapter.fetch = AsyncMock(side_effect=RuntimeError("Connection refused"))
    mock_bronze = AsyncMock(spec=MinioBronzeAdapter)

    async with session_factory() as session:
        use_case = FetchAndWriteUseCase(
            adapter=mock_adapter,
            bronze=mock_bronze,
            fetch_log_repo=FetchLogRepository(session),
            outbox_repo=OutboxRepository(session),
            commit_fn=session.commit,
        )
        summary = await use_case.execute(source, is_backfill=False)

    assert summary.failed == 1
    assert summary.fetched == 0
    assert len(summary.errors) == 1
    assert "Connection refused" in summary.errors[0]


@pytest.mark.asyncio
async def test_pipeline_multiple_articles(session_factory):
    """Pipeline processes multiple articles from a single fetch cycle."""
    source = await _seed_source(session_factory, name="test-multi")

    results = [
        _make_fetch_result(source.id, url=f"https://example.com/article-{i}", url_hash=f"hash_{i}") for i in range(3)
    ]

    mock_adapter = AsyncMock()
    mock_adapter.fetch = AsyncMock(return_value=results)
    mock_bronze = AsyncMock(spec=MinioBronzeAdapter)
    mock_bronze.put_object = AsyncMock(side_effect=[build_bronze_key("eodhd", r.url_hash) for r in results])

    async with session_factory() as session:
        use_case = FetchAndWriteUseCase(
            adapter=mock_adapter,
            bronze=mock_bronze,
            fetch_log_repo=FetchLogRepository(session),
            outbox_repo=OutboxRepository(session),
            commit_fn=session.commit,
        )
        summary = await use_case.execute(source, is_backfill=False)

    assert summary.fetched == 3
    assert summary.skipped == 0

    # Verify 3 fetch_log rows and 3 outbox events
    async with session_factory() as session:
        log_count = (await session.execute(select(func.count()).select_from(FetchLogModel))).scalar()
        outbox_count = (await session.execute(select(func.count()).select_from(OutboxEventModel))).scalar()
        assert log_count == 3
        assert outbox_count == 3
