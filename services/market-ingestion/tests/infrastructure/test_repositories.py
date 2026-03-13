"""Unit + integration tests for DB repositories and UoW (T-MI-17).

Unit tests: mocked SQLAlchemy session — mapper correctness.
Integration tests: marked @pytest.mark.integration — require PostgreSQL.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from market_ingestion.domain.entities.ingestion_task import IngestionTask
from market_ingestion.domain.enums import IngestionTaskStatus, Provider
from market_ingestion.domain.events import MarketDatasetFetched
from market_ingestion.domain.value_objects import DateRange, ObjectRef, Timeframe
from market_ingestion.infrastructure.db.repositories.outbox_repository import (
    _DispatchableOutboxRecord,
)
from market_ingestion.infrastructure.db.repositories.task_repository import (
    SqlaTaskRepository,
    _to_domain,
    _to_model,
)
from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc(year: int = 2024, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


def _make_task(symbol: str = "AAPL") -> IngestionTask:
    return IngestionTask.create_ohlcv_task(
        provider=Provider.EODHD,
        symbol=symbol,
        timeframe=Timeframe("1d"),
        date_range=DateRange(start=_utc(2024, 1, 1), end=_utc(2024, 3, 1)),
    )


def _make_mock_session() -> AsyncMock:
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    session.execute = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# T-MI-17 unit tests — mapper correctness
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_task_to_model_and_back_preserves_fields():
    task = _make_task()
    task.status = IngestionTaskStatus.RUNNING
    task.lease_owner = "worker-1"
    task.attempt_count = 2

    model = _to_model(task)
    assert model.id == task.id
    assert model.provider == "eodhd"
    assert model.symbol == "AAPL"
    assert model.status == "running"
    assert model.locked_by == "worker-1"
    assert model.attempt == 2


@pytest.mark.unit
def test_model_to_domain_maps_status_enum():
    task = _make_task()
    model = _to_model(task)
    model.status = "succeeded"
    model.attempt = 3

    domain = _to_domain(model)
    assert domain.status == IngestionTaskStatus.SUCCEEDED
    assert domain.attempt_count == 3


@pytest.mark.unit
def test_model_to_domain_nullable_fields():
    task = _make_task()
    model = _to_model(task)
    model.exchange = None
    model.timeframe = None
    model.dataset_variant = None

    domain = _to_domain(model)
    assert domain.exchange is None
    assert domain.timeframe is None
    assert domain.variant is None


@pytest.mark.unit
async def test_task_repo_add_many_empty_returns_zero():
    session = _make_mock_session()
    repo = SqlaTaskRepository(write_session=session, read_session=session)
    count = await repo.add_many([])
    assert count == 0


@pytest.mark.unit
async def test_task_repo_get_returns_none_if_not_found():
    session = _make_mock_session()
    session.get = AsyncMock(return_value=None)
    repo = SqlaTaskRepository(write_session=session, read_session=session)
    result = await repo.get("nonexistent-id")
    assert result is None


@pytest.mark.unit
async def test_task_repo_count_by_status_returns_dict():
    session = _make_mock_session()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [("pending", 3), ("running", 1)]
    session.execute = AsyncMock(return_value=mock_result)
    repo = SqlaTaskRepository(write_session=session, read_session=session)
    counts = await repo.count_by_status()
    assert counts == {"pending": 3, "running": 1}


# ---------------------------------------------------------------------------
# Outbox serialization unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_outbox_record_serialization():
    """Verify event.to_dict() is serializable to JSON bytes."""
    ref = ObjectRef(bucket="b", key="k", sha256="a" * 64, byte_length=100, mime_type="application/json")
    event = MarketDatasetFetched(
        provider="eodhd",
        dataset_type="ohlcv",
        symbol="AAPL",
        exchange="US",
        timeframe="1d",
        variant=None,
        range_start=_utc(2024, 1, 1).isoformat(),
        range_end=_utc(2024, 3, 1).isoformat(),
        bronze_ref=ref,
        canonical_ref=ref,
        row_count=10,
        task_id="task-1",
    )
    d = event.to_dict()
    serialized = json.dumps(d).encode("utf-8")
    parsed = json.loads(serialized)
    assert parsed["event_type"] == "market.dataset.fetched"
    assert parsed["symbol"] == "AAPL"


@pytest.mark.unit
def test_dispatchable_outbox_record_exposes_protocol_fields():
    from market_ingestion.application.ports.repositories import OutboxRecord

    record = OutboxRecord(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        topic="market.dataset.fetched",
        key=None,
        payload=json.dumps({"event_type": "market.dataset.fetched", "symbol": "AAPL"}).encode(),
        headers={},
        event_type="market.dataset.fetched",
        created_at=_utc(),
        correlation_id=None,
        attempt=0,
    )
    dispatchable = _DispatchableOutboxRecord.from_outbox_record(record)
    assert dispatchable.event_type == "market.dataset.fetched"
    assert dispatchable.topic == "market.dataset.fetched"
    assert dispatchable.payload == {"event_type": "market.dataset.fetched", "symbol": "AAPL"}
    assert dispatchable.attempts == 0
    assert dispatchable.leased_until is None


# ---------------------------------------------------------------------------
# UoW unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_uow_on_commit_callback_is_invoked():
    called = []

    write_factory = MagicMock()
    write_session = AsyncMock()
    write_session.commit = AsyncMock()
    write_session.__aenter__ = AsyncMock(return_value=write_session)
    write_session.__aexit__ = AsyncMock(return_value=None)
    write_factory.return_value = write_session

    uow = SqlaUnitOfWork(write_factory)
    async with uow:
        uow.on_commit(lambda: called.append(True))
        await uow.commit()

    assert called == [True]


@pytest.mark.unit
async def test_uow_rollback_clears_on_exception():
    write_factory = MagicMock()
    write_session = AsyncMock()
    write_session.__aenter__ = AsyncMock(return_value=write_session)
    write_session.__aexit__ = AsyncMock(return_value=None)
    write_factory.return_value = write_session

    uow = SqlaUnitOfWork(write_factory)
    try:
        async with uow:
            raise ValueError("intentional")
    except ValueError:
        pass

    write_session.rollback.assert_awaited()


@pytest.mark.unit
async def test_uow_repositories_accessible_inside_context():
    write_factory = MagicMock()
    write_session = AsyncMock()
    write_session.__aenter__ = AsyncMock(return_value=write_session)
    write_session.__aexit__ = AsyncMock(return_value=None)
    write_factory.return_value = write_session

    uow = SqlaUnitOfWork(write_factory)
    async with uow:
        assert uow.tasks is not None
        assert uow.watermarks is not None
        assert uow.policies is not None
        assert uow.budgets is not None
        assert uow.outbox is not None


@pytest.mark.unit
async def test_uow_mark_outbox_events_added():
    write_factory = MagicMock()
    write_session = AsyncMock()
    write_session.__aenter__ = AsyncMock(return_value=write_session)
    write_session.__aexit__ = AsyncMock(return_value=None)
    write_factory.return_value = write_session

    uow = SqlaUnitOfWork(write_factory)
    async with uow:
        assert not uow.has_outbox_events
        uow.mark_outbox_events_added()
        assert uow.has_outbox_events


# ---------------------------------------------------------------------------
# Integration tests (require PostgreSQL)
# ---------------------------------------------------------------------------

_NEEDS_DB = pytest.mark.skipif(
    not os.getenv("MARKET_INGESTION_DATABASE_URL", "").startswith("postgresql"),
    reason="Requires live PostgreSQL (set MARKET_INGESTION_DATABASE_URL)",
)


@pytest.mark.integration
@_NEEDS_DB
async def test_integration_task_add_and_claim(settings):
    """Task add + claim roundtrip with real Postgres."""
    import time

    from market_ingestion.infrastructure.db.session import _build_factories

    write_factory, read_factory = _build_factories(settings)
    task = _make_task(f"IT_ADD_{int(time.time_ns())}")

    uow = SqlaUnitOfWork(write_factory, read_factory)
    async with uow:
        await uow.tasks.add(task)
        await uow.commit()

    async with SqlaUnitOfWork(write_factory, read_factory) as uow2:
        claimed = await uow2.tasks.claim_batch(worker_id="test-worker", limit=100, lease_seconds=60)
        assert any(t.id == task.id for t in claimed)
        await uow2.commit()


@pytest.mark.integration
@_NEEDS_DB
async def test_integration_idempotent_task_enqueue(settings):
    """Same dedupe_key → no duplicate row, no error."""
    import time

    from market_ingestion.infrastructure.db.session import _build_factories

    write_factory, read_factory = _build_factories(settings)
    task = _make_task(f"IT_IDEM_{int(time.time_ns())}")

    async with SqlaUnitOfWork(write_factory, read_factory) as uow:
        count1 = await uow.tasks.add_many([task])
        count2 = await uow.tasks.add_many([task])
        await uow.commit()

    assert count1 == 1
    assert count2 == 0  # ON CONFLICT DO NOTHING


@pytest.mark.integration
@_NEEDS_DB
async def test_integration_uow_commit_and_rollback(settings):
    """Write then rollback → no row persisted."""
    import time

    from market_ingestion.infrastructure.db.session import _build_factories

    write_factory, read_factory = _build_factories(settings)
    task = _make_task(f"IT_ROLL_{int(time.time_ns())}")

    async with SqlaUnitOfWork(write_factory, read_factory) as uow:
        await uow.tasks.add(task)
        await uow.rollback()

    async with SqlaUnitOfWork(write_factory, read_factory) as uow2:
        result = await uow2.tasks.get(task.id)
        assert result is None
