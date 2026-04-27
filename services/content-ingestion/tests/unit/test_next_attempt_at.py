"""Unit tests for the next_attempt_at retry-backoff field (W2-12).

Covers:
  - Domain entity accepts and stores next_attempt_at
  - ORM model declares the column
  - Repository _to_domain correctly maps the column
  - Repository add() passes next_attempt_at to the ORM model
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from content_ingestion.domain.entities import ContentIngestionTask
from content_ingestion.infrastructure.db.models import ContentIngestionTaskModel
from content_ingestion.infrastructure.db.repositories.task import TaskRepository

import common.ids
import common.time
from contracts.enums import ContentSourceType as SourceType  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Domain entity tests
# ---------------------------------------------------------------------------


class TestContentIngestionTaskNextAttemptAt:
    def test_field_defaults_to_none(self) -> None:
        """next_attempt_at is None by default — task is immediately claimable."""
        task = ContentIngestionTask(
            source_id=common.ids.new_uuid7(),
            source_name="eodhd-news",
            source_type=SourceType.EODHD,
        )
        assert task.next_attempt_at is None

    def test_field_accepts_datetime(self) -> None:
        """next_attempt_at stores a UTC-aware datetime when provided."""
        future = datetime.now(tz=UTC) + timedelta(seconds=60)
        task = ContentIngestionTask(
            source_id=common.ids.new_uuid7(),
            source_name="eodhd-news",
            source_type=SourceType.EODHD,
            next_attempt_at=future,
        )
        assert task.next_attempt_at == future

    def test_field_accepts_none_explicitly(self) -> None:
        """next_attempt_at can be set to None explicitly."""
        task = ContentIngestionTask(
            source_id=common.ids.new_uuid7(),
            source_name="eodhd-news",
            source_type=SourceType.EODHD,
            next_attempt_at=None,
        )
        assert task.next_attempt_at is None


# ---------------------------------------------------------------------------
# ORM model tests
# ---------------------------------------------------------------------------


class TestOrmModelNextAttemptAt:
    def test_orm_model_declares_column(self) -> None:
        """ContentIngestionTaskModel has a next_attempt_at column."""
        assert hasattr(ContentIngestionTaskModel, "next_attempt_at")

    def test_orm_model_column_is_nullable(self) -> None:
        """The column is declared as nullable=True."""
        col = ContentIngestionTaskModel.__table__.c["next_attempt_at"]
        assert col.nullable is True

    def test_orm_model_column_is_timestamptz(self) -> None:
        """The column uses a timezone-aware TIMESTAMP type."""
        col = ContentIngestionTaskModel.__table__.c["next_attempt_at"]
        # TIMESTAMP(timezone=True) → .timezone attribute is True
        assert col.type.timezone is True


# ---------------------------------------------------------------------------
# Repository mapping tests
# ---------------------------------------------------------------------------


def _make_mock_row(next_attempt_at: datetime | None = None) -> MagicMock:
    """Build a minimal MagicMock ORM row for _to_domain mapping tests."""
    now = common.time.utc_now()
    row = MagicMock()
    row.id = common.ids.new_uuid7()
    row.source_id = common.ids.new_uuid7()
    row.source_name = "eodhd-news"
    row.source_type = "eodhd"
    row.status = "pending"
    row.worker_id = None
    row.leased_at = None
    row.lease_expires = None
    row.attempt_count = 0
    row.max_attempts = 5
    row.error_detail = None
    row.is_backfill = False
    row.window_start = None
    row.next_attempt_at = next_attempt_at
    row.created_at = now
    row.updated_at = now
    return row


def _mock_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    return session


class TestRepositoryNextAttemptAtMapping:
    async def test_add_passes_next_attempt_at_to_orm(self) -> None:
        """repo.add() passes next_attempt_at from domain entity to the ORM model."""
        future = datetime.now(tz=UTC) + timedelta(seconds=120)
        task = ContentIngestionTask(
            source_id=common.ids.new_uuid7(),
            source_name="eodhd-news",
            source_type=SourceType.EODHD,
            next_attempt_at=future,
        )

        session = _mock_session()
        repo = TaskRepository(session)  # type: ignore[arg-type]
        await repo.add(task)

        session.add.assert_called_once()
        orm_model = session.add.call_args[0][0]
        assert orm_model.next_attempt_at == future

    async def test_add_passes_none_next_attempt_at(self) -> None:
        """repo.add() passes next_attempt_at=None when not set."""
        task = ContentIngestionTask(
            source_id=common.ids.new_uuid7(),
            source_name="eodhd-news",
            source_type=SourceType.EODHD,
        )

        session = _mock_session()
        repo = TaskRepository(session)  # type: ignore[arg-type]
        await repo.add(task)

        orm_model = session.add.call_args[0][0]
        assert orm_model.next_attempt_at is None

    async def test_claim_batch_maps_next_attempt_at(self) -> None:
        """_to_domain() correctly maps next_attempt_at from ORM row to domain entity."""
        future = datetime.now(tz=UTC) + timedelta(seconds=300)
        mock_row = _make_mock_row(next_attempt_at=future)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_row]

        session = _mock_session()
        session.execute.return_value = mock_result

        repo = TaskRepository(session)  # type: ignore[arg-type]
        tasks = await repo.claim_batch(worker_id="w1", limit=5, lease_seconds=300)

        assert len(tasks) == 1
        assert tasks[0].next_attempt_at == future

    async def test_claim_batch_maps_none_next_attempt_at(self) -> None:
        """_to_domain() maps next_attempt_at=None correctly (most common case)."""
        mock_row = _make_mock_row(next_attempt_at=None)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_row]

        session = _mock_session()
        session.execute.return_value = mock_result

        repo = TaskRepository(session)  # type: ignore[arg-type]
        tasks = await repo.claim_batch(worker_id="w1", limit=5, lease_seconds=300)

        assert len(tasks) == 1
        assert tasks[0].next_attempt_at is None
