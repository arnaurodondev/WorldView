"""Integration tests for S4 idempotency guarantees (T-A-4-03).

Validates: same URL submitted twice → exactly 1 fetch_log row + 1 outbox event.

Requires live PostgreSQL.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from content_ingestion.application.use_cases.fetch_and_write import FetchAndWriteUseCase
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


async def _seed_source(session_factory, name="test-dedup") -> Source:
    """Insert a source into the DB and return a domain Source with the DB-generated ID."""
    async with session_factory() as session:
        repo = SourceRepository(session)
        model = await repo.create(name=name, source_type="eodhd", config={}, enabled=True)
        await session.commit()
        return Source(
            id=model.id,
            name=model.name,
            source_type=SourceType(model.source_type),
            enabled=model.enabled,
            config=model.config,
            created_at=model.created_at,
        )


def _make_fetch_result(source_id, url_hash="duplicate_hash_001"):
    return FetchResult(
        source_id=source_id,
        url="https://example.com/duplicate-article",
        url_hash=url_hash,
        raw_bytes=b'{"title": "Duplicate Test"}',
        fetched_at=common.time.utc_now(),
        http_status=200,
        content_type="application/json",
        published_at=datetime(2026, 3, 25, tzinfo=UTC),
        is_backfill=False,
    )


@pytest.mark.asyncio
async def test_same_url_twice_produces_exactly_one_record(session_factory):
    """Submitting the same url_hash twice → 1 fetch_log + 1 outbox, second is skipped."""
    source = await _seed_source(session_factory)
    result = _make_fetch_result(source.id)

    mock_adapter = AsyncMock()
    mock_adapter.fetch = AsyncMock(return_value=[result])
    mock_bronze = AsyncMock(spec=MinioBronzeAdapter)
    mock_bronze.put_object = AsyncMock(return_value=build_bronze_key("eodhd", result.url_hash))

    # First execution — should insert
    async with session_factory() as session:
        use_case = FetchAndWriteUseCase(
            adapter=mock_adapter,
            bronze=mock_bronze,
            fetch_log_repo=FetchLogRepository(session),
            outbox_repo=OutboxRepository(session),
            commit_fn=session.commit,
        )
        summary1 = await use_case.execute(source, is_backfill=False)

    assert summary1.fetched == 1
    assert summary1.skipped == 0

    # Second execution — same url_hash should be skipped
    async with session_factory() as session:
        use_case = FetchAndWriteUseCase(
            adapter=mock_adapter,
            bronze=mock_bronze,
            fetch_log_repo=FetchLogRepository(session),
            outbox_repo=OutboxRepository(session),
            commit_fn=session.commit,
        )
        summary2 = await use_case.execute(source, is_backfill=False)

    assert summary2.fetched == 0
    assert summary2.skipped == 1

    # Verify exactly 1 fetch_log row
    async with session_factory() as session:
        log_count = (await session.execute(select(func.count()).select_from(FetchLogModel))).scalar()
        assert log_count == 1

    # Verify exactly 1 outbox event
    async with session_factory() as session:
        outbox_count = (await session.execute(select(func.count()).select_from(OutboxEventModel))).scalar()
        assert outbox_count == 1


@pytest.mark.asyncio
async def test_different_url_hashes_produce_separate_records(session_factory):
    """Two articles with different url_hashes both get stored."""
    source = await _seed_source(session_factory, name="test-dedup-diff")

    result_a = _make_fetch_result(source.id, url_hash="hash_a")
    result_b = _make_fetch_result(source.id, url_hash="hash_b")

    mock_bronze = AsyncMock(spec=MinioBronzeAdapter)
    mock_bronze.put_object = AsyncMock(
        side_effect=[build_bronze_key("eodhd", "hash_a"), build_bronze_key("eodhd", "hash_b")]
    )

    # First: insert result_a
    mock_adapter_a = AsyncMock()
    mock_adapter_a.fetch = AsyncMock(return_value=[result_a])
    async with session_factory() as session:
        use_case = FetchAndWriteUseCase(
            adapter=mock_adapter_a,
            bronze=mock_bronze,
            fetch_log_repo=FetchLogRepository(session),
            outbox_repo=OutboxRepository(session),
            commit_fn=session.commit,
        )
        s1 = await use_case.execute(source, is_backfill=False)
    assert s1.fetched == 1

    # Second: insert result_b (different hash — should also be inserted)
    mock_adapter_b = AsyncMock()
    mock_adapter_b.fetch = AsyncMock(return_value=[result_b])
    async with session_factory() as session:
        use_case = FetchAndWriteUseCase(
            adapter=mock_adapter_b,
            bronze=mock_bronze,
            fetch_log_repo=FetchLogRepository(session),
            outbox_repo=OutboxRepository(session),
            commit_fn=session.commit,
        )
        s2 = await use_case.execute(source, is_backfill=False)
    assert s2.fetched == 1

    # Both should be present
    async with session_factory() as session:
        log_count = (await session.execute(select(func.count()).select_from(FetchLogModel))).scalar()
        assert log_count == 2
        outbox_count = (await session.execute(select(func.count()).select_from(OutboxEventModel))).scalar()
        assert outbox_count == 2


@pytest.mark.asyncio
async def test_batch_with_duplicate_in_same_cycle(session_factory):
    """A batch containing two results with the same url_hash produces only 1 record."""
    source = await _seed_source(session_factory, name="test-dedup-batch")

    same_hash = "same_hash_in_batch"
    result1 = _make_fetch_result(source.id, url_hash=same_hash)
    result2 = _make_fetch_result(source.id, url_hash=same_hash)

    mock_adapter = AsyncMock()
    mock_adapter.fetch = AsyncMock(return_value=[result1, result2])
    mock_bronze = AsyncMock(spec=MinioBronzeAdapter)
    mock_bronze.put_object = AsyncMock(return_value=build_bronze_key("eodhd", same_hash))

    async with session_factory() as session:
        use_case = FetchAndWriteUseCase(
            adapter=mock_adapter,
            bronze=mock_bronze,
            fetch_log_repo=FetchLogRepository(session),
            outbox_repo=OutboxRepository(session),
            commit_fn=session.commit,
        )
        summary = await use_case.execute(source, is_backfill=False)

    assert summary.fetched == 1
    assert summary.skipped == 1

    async with session_factory() as session:
        log_count = (await session.execute(select(func.count()).select_from(FetchLogModel))).scalar()
        assert log_count == 1
