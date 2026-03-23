"""Unit tests for Content Ingestion repositories (mock async session)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from content_ingestion.infrastructure.db.models import (
    DLQEventModel,
    FetchLogModel,
    OutboxEventModel,
    SourceModel,
)
from content_ingestion.infrastructure.db.repositories.fetch_log import FetchLogRepository
from content_ingestion.infrastructure.db.repositories.outbox import OutboxRepository
from content_ingestion.infrastructure.db.repositories.source import SourceRepository

import common.time

pytestmark = pytest.mark.unit


def _mock_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# FetchLogRepository
# ---------------------------------------------------------------------------


class TestFetchLogRepository:
    def test_create_adds_model(self) -> None:
        session = _mock_session()
        repo = FetchLogRepository(session)  # type: ignore[arg-type]
        import asyncio

        asyncio.get_event_loop().run_until_complete(
            repo.create(
                url="https://example.com/a",
                url_hash="abc123",
                source_id=UUID("00000000-0000-0000-0000-000000000001"),
                http_status=200,
                byte_size=100,
                fetched_at=common.time.utc_now(),
            )
        )
        session.add.assert_called_once()
        added = session.add.call_args[0][0]
        assert isinstance(added, FetchLogModel)
        assert added.url_hash == "abc123"

    async def test_exists_by_url_hash_true(self) -> None:
        session = _mock_session()
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = UUID("00000000-0000-0000-0000-000000000002")
        session.execute = AsyncMock(return_value=scalar_result)
        repo = FetchLogRepository(session)  # type: ignore[arg-type]
        result = await repo.exists_by_url_hash("abc123")
        assert result is True

    async def test_exists_by_url_hash_false(self) -> None:
        session = _mock_session()
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=scalar_result)
        repo = FetchLogRepository(session)  # type: ignore[arg-type]
        result = await repo.exists_by_url_hash("notfound")
        assert result is False


# ---------------------------------------------------------------------------
# OutboxRepository
# ---------------------------------------------------------------------------


class TestOutboxRepository:
    def test_append_adds_model(self) -> None:
        session = _mock_session()
        repo = OutboxRepository(session)  # type: ignore[arg-type]
        import asyncio

        asyncio.get_event_loop().run_until_complete(
            repo.append(
                aggregate_type="RawArticle",
                aggregate_id=UUID("00000000-0000-0000-0000-000000000003"),
                event_type="article.raw.v1",
                payload={"article_id": "xyz"},
            )
        )
        session.add.assert_called_once()
        added = session.add.call_args[0][0]
        assert isinstance(added, OutboxEventModel)
        assert added.aggregate_type == "RawArticle"
        assert added.payload == {"article_id": "xyz"}

    async def test_mark_dispatched_sets_status(self) -> None:
        event_id = UUID("00000000-0000-0000-0000-000000000004")
        event = OutboxEventModel(
            id=event_id,
            aggregate_type="RawArticle",
            aggregate_id=UUID("00000000-0000-0000-0000-000000000005"),
            event_type="article.raw.v1",
            payload={},
            status="pending",
            retry_count=0,
        )
        session = _mock_session()
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = event
        session.execute = AsyncMock(return_value=scalar_result)
        repo = OutboxRepository(session)  # type: ignore[arg-type]
        await repo.mark_dispatched(event_id)
        assert event.status == "dispatched"
        assert event.dispatched_at is not None

    async def test_move_to_dlq_inserts_and_deletes(self) -> None:
        event_id = UUID("00000000-0000-0000-0000-000000000006")
        event = OutboxEventModel(
            id=event_id,
            aggregate_type="RawArticle",
            aggregate_id=UUID("00000000-0000-0000-0000-000000000007"),
            event_type="article.raw.v1",
            payload={"article_id": "abc"},
            status="failed",
            retry_count=3,
            error="timeout",
        )
        session = _mock_session()
        call_count = 0

        async def _execute_side_effect(stmt):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            result.scalar_one_or_none.return_value = event if call_count == 1 else None
            return result

        session.execute = AsyncMock(side_effect=_execute_side_effect)
        repo = OutboxRepository(session)  # type: ignore[arg-type]
        await repo.move_to_dlq(event_id)
        session.add.assert_called_once()
        dlq = session.add.call_args[0][0]
        assert isinstance(dlq, DLQEventModel)
        assert dlq.original_event_id == event_id
        # DELETE was executed
        assert call_count == 2


# ---------------------------------------------------------------------------
# SourceRepository
# ---------------------------------------------------------------------------


class TestSourceRepository:
    async def test_get_all_returns_list(self) -> None:
        sources = [
            SourceModel(
                id=UUID("00000000-0000-0000-0000-000000000008"),
                name="eodhd",
                source_type="eodhd",
                enabled=True,
                config={},
            )
        ]
        session = _mock_session()
        scalars_result = MagicMock()
        scalars_result.all.return_value = sources
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_result
        session.execute = AsyncMock(return_value=execute_result)
        repo = SourceRepository(session)  # type: ignore[arg-type]
        result = await repo.get_all()
        assert result == sources
