"""Unit tests for content-ingestion repositories (async session mocked)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from content_ingestion.infrastructure.db.models import FetchLogModel, OutboxEventModel, SourceModel
from content_ingestion.infrastructure.db.repositories.fetch_log import FetchLogRepository
from content_ingestion.infrastructure.db.repositories.outbox import OutboxRepository
from content_ingestion.infrastructure.db.repositories.source import SourceRepository

import common.time

pytestmark = pytest.mark.unit


def _mock_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    return session


class TestFetchLogRepository:
    async def test_create_adds_model(self) -> None:
        session = _mock_session()
        repo = FetchLogRepository(session)  # type: ignore[arg-type]

        await repo.create(
            url="https://example.com/a",
            url_hash="abc123",
            source_id=UUID("00000000-0000-0000-0000-000000000001"),
            http_status=200,
            byte_size=100,
            fetched_at=common.time.utc_now(),
        )

        session.add.assert_called_once()
        added = session.add.call_args[0][0]
        assert isinstance(added, FetchLogModel)
        assert added.url_hash == "abc123"

    async def test_exists_by_url_hash_true(self) -> None:
        session = _mock_session()
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = UUID("00000000-0000-0000-0000-000000000002")
        session.execute.return_value = scalar_result
        repo = FetchLogRepository(session)  # type: ignore[arg-type]

        result = await repo.exists_by_url_hash("abc123")

        assert result is True


class TestOutboxRepository:
    async def test_append_adds_model(self) -> None:
        session = _mock_session()
        repo = OutboxRepository(session)  # type: ignore[arg-type]

        await repo.append(
            aggregate_type="RawArticle",
            aggregate_id=UUID("00000000-0000-0000-0000-000000000003"),
            event_type="content.article.raw.v1",
            topic="content.article.raw.v1",
            payload={"article_id": "xyz"},
        )

        session.add.assert_called_once()
        added = session.add.call_args[0][0]
        assert isinstance(added, OutboxEventModel)
        assert added.aggregate_type == "RawArticle"
        assert added.status in (None, "pending")

    async def test_fetch_pending_claims_records(self) -> None:
        session = _mock_session()
        record = OutboxEventModel(
            id=UUID("00000000-0000-0000-0000-000000000010"),
            aggregate_type="RawArticle",
            aggregate_id=UUID("00000000-0000-0000-0000-000000000011"),
            event_type="content.article.raw.v1",
            topic="content.article.raw.v1",
            payload={},
            status="pending",
            attempts=0,
            max_attempts=5,
        )
        result = MagicMock()
        result.scalars.return_value.all.return_value = [record]
        session.execute.return_value = result

        repo = OutboxRepository(session)  # type: ignore[arg-type]
        claimed = await repo.fetch_pending(worker_id="worker-1", lease_seconds=30, batch_size=10)

        assert claimed == [record]
        assert record.status == "processing"
        assert record.lease_owner == "worker-1"
        session.flush.assert_awaited()

    async def test_mark_published_executes_update(self) -> None:
        session = _mock_session()
        repo = OutboxRepository(session)  # type: ignore[arg-type]

        await repo.mark_published(UUID("00000000-0000-0000-0000-000000000012"))

        session.execute.assert_awaited_once()

    async def test_increment_attempts_executes_update(self) -> None:
        session = _mock_session()
        repo = OutboxRepository(session)  # type: ignore[arg-type]

        await repo.increment_attempts(UUID("00000000-0000-0000-0000-000000000013"))

        session.execute.assert_awaited_once()

    async def test_move_to_dead_letter_executes_update(self) -> None:
        session = _mock_session()
        repo = OutboxRepository(session)  # type: ignore[arg-type]

        await repo.move_to_dead_letter(UUID("00000000-0000-0000-0000-000000000014"))

        session.execute.assert_awaited_once()


class TestSourceRepository:
    async def test_get_all_returns_list(self) -> None:
        session = _mock_session()
        execute_result = MagicMock()
        execute_result.scalars.return_value.all.return_value = [
            SourceModel(
                id=UUID("00000000-0000-0000-0000-000000000008"),
                name="eodhd",
                source_type="eodhd",
                enabled=True,
                config={},
            )
        ]
        session.execute.return_value = execute_result

        repo = SourceRepository(session)  # type: ignore[arg-type]
        result = await repo.get_all()

        assert len(result) == 1
        assert result[0].name == "eodhd"
