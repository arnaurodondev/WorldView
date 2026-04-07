"""Unit + integration tests for DB repositories and UoW (T-MI-17).

Unit tests: mocked SQLAlchemy session — mapper correctness.
Integration tests: marked @pytest.mark.integration — require PostgreSQL.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from market_ingestion.domain.entities.ingestion_task import IngestionTask
from market_ingestion.domain.enums import IngestionTaskStatus, Provider
from market_ingestion.domain.events import MarketDatasetFetched
from market_ingestion.domain.value_objects import DateRange, ObjectRef, Timeframe
from market_ingestion.infrastructure.db.models.polling_policy import PollingPolicyModel
from market_ingestion.infrastructure.db.repositories.outbox_repository import (
    _DispatchableOutboxRecord,
)
from market_ingestion.infrastructure.db.repositories.policy_repository import (
    _to_domain as policy_to_domain,
)
from market_ingestion.infrastructure.db.repositories.task_repository import (
    SqlaTaskRepository,
    _to_domain,
    _to_model,
)
from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork
from sqlalchemy.dialects import postgresql

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
def test_policy_model_to_domain_maps_backfill_fields() -> None:
    model = PollingPolicyModel(
        id="01HXSEED000000000000000001",
        provider="eodhd",
        dataset_type="ohlcv",
        dataset_variant=None,
        symbol="AAPL",
        exchange="US",
        timeframe="1d",
        base_interval_sec=3600,
        min_interval_sec=60,
        jitter_sec=10,
        adaptive_enabled=False,
        adaptive_k=1.0,
        adaptive_half_life_sec=3600,
        priority=5,
        enabled=True,
        backfill_enabled=True,
        backfill_start_date=date(2020, 1, 1),
        backfill_chunk_days=30,
        created_at=_utc(2024, 1, 1),
        updated_at=_utc(2024, 1, 1),
    )

    domain = policy_to_domain(model)

    assert domain.backfill_enabled is True
    assert domain.backfill_start_date == date(2020, 1, 1)
    assert domain.backfill_days == 30


@pytest.mark.unit
def test_policy_model_to_domain_keeps_backfill_disabled() -> None:
    model = PollingPolicyModel(
        id="01HXSEED000000000000000002",
        provider="eodhd",
        dataset_type="ohlcv",
        dataset_variant=None,
        symbol="AAPL",
        exchange="US",
        timeframe="1d",
        base_interval_sec=3600,
        min_interval_sec=60,
        jitter_sec=10,
        adaptive_enabled=False,
        adaptive_k=1.0,
        adaptive_half_life_sec=3600,
        priority=5,
        enabled=True,
        backfill_enabled=False,
        backfill_start_date=date(2020, 1, 1),
        backfill_chunk_days=30,
        created_at=_utc(2024, 1, 1),
        updated_at=_utc(2024, 1, 1),
    )

    domain = policy_to_domain(model)

    assert domain.backfill_enabled is False


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


@pytest.mark.unit
async def test_task_repo_has_active_task_uses_is_null_for_nullable_tuple_fields():
    session = _make_mock_session()
    mock_result = MagicMock()
    mock_result.first.return_value = None
    session.execute = AsyncMock(return_value=mock_result)

    repo = SqlaTaskRepository(write_session=session, read_session=session)
    found = await repo.has_active_task(
        provider=Provider.EODHD,
        dataset_type=_make_task().dataset_type,
        symbol="AAPL",
        exchange=None,
        timeframe="1d",
        variant=None,
    )

    assert found is False
    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "exchange IS NULL" in sql
    assert "dataset_variant IS NULL" in sql


# ---------------------------------------------------------------------------
# T-E1-3-01: claim_batch CTE atomicity (M-006)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_claim_batch_atomic_cte_no_race_window() -> None:
    """claim_batch uses a single CTE+UPDATE statement, not SELECT-then-UPDATE.

    The CTE selects candidates (FOR UPDATE SKIP LOCKED) and the UPDATE operates on
    the locked set in one SQL round-trip, closing the race window (M-006).
    """
    session = _make_mock_session()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)

    repo = SqlaTaskRepository(write_session=session, read_session=session)
    result = await repo.claim_batch(worker_id="w1", limit=5, lease_seconds=60)

    # Only ONE execute call — the CTE+UPDATE is a single statement
    assert session.execute.await_count == 1
    assert result == []

    # The statement must be an UPDATE (not a SELECT)
    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": False}))
    assert "UPDATE" in sql.upper()
    assert "candidates" in sql  # CTE name present


# ---------------------------------------------------------------------------
# T-E1-1-02: result_ref + completed_at round-trip tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_save_persists_result_ref_on_success() -> None:
    """After task.succeed(ref), save() includes result_ref columns in UPDATE."""
    session = _make_mock_session()
    mock_result = MagicMock()
    session.execute = AsyncMock(return_value=mock_result)

    task = _make_task()
    task.status = IngestionTaskStatus.RUNNING
    ref = ObjectRef(
        bucket="market-bronze", key="raw/task-1", sha256="a" * 64, byte_length=512, mime_type="application/json"
    )
    task.result_ref = ref

    repo = SqlaTaskRepository(write_session=session, read_session=session)
    await repo.save(task)

    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "market-bronze" in sql
    assert "raw/task-1" in sql
    assert "a" * 64 in sql


@pytest.mark.unit
async def test_save_completed_at_set_on_success() -> None:
    """completed_at is included in the UPDATE statement after task.succeed()."""
    session = _make_mock_session()
    mock_result = MagicMock()
    session.execute = AsyncMock(return_value=mock_result)

    task = _make_task()
    task.status = IngestionTaskStatus.SUCCEEDED
    task.completed_at = _utc(2026, 3, 27)

    repo = SqlaTaskRepository(write_session=session, read_session=session)
    await repo.save(task)

    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    # completed_at must be in the UPDATE SET clause
    assert "completed_at" in str(compiled)


@pytest.mark.unit
async def test_save_result_ref_none_on_pending_task() -> None:
    """Pending task has null result_ref columns — UPDATE sets them to NULL."""
    session = _make_mock_session()
    mock_result = MagicMock()
    session.execute = AsyncMock(return_value=mock_result)

    task = _make_task()
    assert task.result_ref is None

    repo = SqlaTaskRepository(write_session=session, read_session=session)
    await repo.save(task)

    stmt = session.execute.call_args.args[0]
    # Inspect the VALUES dict — all result_ref columns should be None
    update_params = stmt.compile(dialect=postgresql.dialect()).params
    assert update_params.get("result_ref_bucket_1") is None
    assert update_params.get("result_ref_key_1") is None


@pytest.mark.unit
def test_to_domain_reconstructs_result_ref_from_columns() -> None:
    """_to_domain() rebuilds ObjectRef when bucket+key columns are populated."""
    task = _make_task()
    model = _to_model(task)
    model.status = "succeeded"
    model.result_ref_bucket = "market-bronze"
    model.result_ref_key = "raw/task-1"
    model.result_ref_sha256 = "b" * 64
    model.result_ref_mime_type = "application/json"
    model.completed_at = _utc(2026, 3, 27)

    domain = _to_domain(model)

    assert domain.result_ref is not None
    assert domain.result_ref.bucket == "market-bronze"
    assert domain.result_ref.key == "raw/task-1"
    assert domain.result_ref.sha256 == "b" * 64
    assert domain.completed_at == _utc(2026, 3, 27)


@pytest.mark.unit
def test_to_domain_result_ref_none_when_columns_null() -> None:
    """_to_domain() returns result_ref=None when columns are NULL."""
    task = _make_task()
    model = _to_model(task)
    model.result_ref_bucket = None
    model.result_ref_key = None

    domain = _to_domain(model)
    assert domain.result_ref is None


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
# T-E1-2-03: UoW __aexit__ session cleanup (BP-037)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_uow_close_sessions_always_called_on_rollback_failure() -> None:
    """_close_sessions() runs even if rollback() raises — BP-037."""
    write_factory = MagicMock()
    write_session = AsyncMock()
    write_session.__aenter__ = AsyncMock(return_value=write_session)
    write_session.__aexit__ = AsyncMock(return_value=None)
    # rollback raises — _close_sessions must still run
    write_session.rollback = AsyncMock(side_effect=RuntimeError("rollback failed"))
    write_factory.return_value = write_session

    uow = SqlaUnitOfWork(write_factory)
    # Enter, then exit with an exception to trigger rollback path
    try:
        async with uow:
            raise ValueError("business error")
    except ValueError:
        pass

    # __aexit__ calls _write_session.__aexit__ (which is _close_sessions)
    write_session.__aexit__.assert_awaited()


@pytest.mark.unit
async def test_uow_original_exception_logged_on_rollback_failure() -> None:
    """When rollback() raises, the original exc info is preserved in the log."""
    from unittest.mock import patch

    write_factory = MagicMock()
    write_session = AsyncMock()
    write_session.__aenter__ = AsyncMock(return_value=write_session)
    write_session.__aexit__ = AsyncMock(return_value=None)
    write_session.rollback = AsyncMock(side_effect=RuntimeError("db gone"))
    write_factory.return_value = write_session

    with patch("market_ingestion.infrastructure.db.unit_of_work.logger") as mock_logger:
        try:
            uow = SqlaUnitOfWork(write_factory)
            async with uow:
                raise ValueError("original error")
        except ValueError:
            pass

        # logger.error should be called with the original exc in repr
        mock_logger.error.assert_called_once()
        call_kwargs = mock_logger.error.call_args
        assert "original" in call_kwargs.kwargs or len(call_kwargs.args) > 0
        logged_original = call_kwargs.kwargs.get("original", "")
        assert "original error" in logged_original or "ValueError" in logged_original


# ---------------------------------------------------------------------------
# T-E1-2-04: Outbox _get_topic guard (BP-039)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_outbox_get_topic_raises_on_unknown_event_type() -> None:
    """_get_topic() raises ValueError for unregistered event types — BP-039."""
    from market_ingestion.infrastructure.db.repositories.outbox_repository import _get_topic

    with pytest.raises(ValueError, match="Unknown event_type"):
        _get_topic("completely.unknown.event")


@pytest.mark.unit
def test_outbox_get_topic_returns_correct_topic_for_known_event() -> None:
    """_get_topic() resolves the correct topic for market.dataset.fetched."""
    from market_ingestion.infrastructure.db.repositories.outbox_repository import _get_topic

    topic = _get_topic("market.dataset.fetched")
    assert topic  # non-empty string
    assert "market" in topic  # either the canonical name or messaging lib value


# ---------------------------------------------------------------------------
# N-009: Lease-owner guard in save()
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_save_respects_lease_owner() -> None:
    """save() with wrong lease_owner produces rowcount==0 and logs a warning (N-009).

    The WHERE clause includes:
        locked_by == task.lease_owner OR locked_by IS NULL
    so a task held by a different worker is not overwritten.
    """
    session = _make_mock_session()
    mock_result = MagicMock()
    mock_result.rowcount = 0  # simulate stale-worker mismatch
    session.execute = AsyncMock(return_value=mock_result)

    task = _make_task()
    task.lease_owner = "worker-A"

    repo = SqlaTaskRepository(write_session=session, read_session=session)

    with patch("market_ingestion.infrastructure.db.repositories.task_repository.logger") as mock_log:
        await repo.save(task)

    # Warning must be emitted when rowcount == 0
    mock_log.warning.assert_called_once()
    call_kwargs = mock_log.warning.call_args
    event_name = call_kwargs[0][0]
    assert event_name == "task_save_lease_mismatch"


@pytest.mark.unit
async def test_save_lease_guard_where_clause_contains_locked_by() -> None:
    """save() WHERE clause must reference locked_by for lease-owner guard (N-009)."""
    session = _make_mock_session()
    mock_result = MagicMock()
    mock_result.rowcount = 1
    session.execute = AsyncMock(return_value=mock_result)

    task = _make_task()
    task.lease_owner = "worker-B"

    repo = SqlaTaskRepository(write_session=session, read_session=session)
    await repo.save(task)

    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    # The WHERE clause must include a locked_by condition
    assert "locked_by" in sql


@pytest.mark.unit
async def test_save_no_warning_when_rowcount_positive() -> None:
    """save() must NOT log a warning when the UPDATE affects at least one row."""
    session = _make_mock_session()
    mock_result = MagicMock()
    mock_result.rowcount = 1  # successful update
    session.execute = AsyncMock(return_value=mock_result)

    task = _make_task()
    task.lease_owner = "worker-C"

    repo = SqlaTaskRepository(write_session=session, read_session=session)

    with patch("market_ingestion.infrastructure.db.repositories.task_repository.logger") as mock_log:
        await repo.save(task)

    mock_log.warning.assert_not_called()


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
