"""Unit tests for PrimaryProviderReclaimWorker.

Covers:
- Reclaim identifies tasks fetched by secondary (non-primary) provider
- _make_reclaim_task() creates a new task targeting the primary provider
- Same dedupe_key guarantees idempotency (ON CONFLICT DO NOTHING)
- Tasks with fetched_by_provider=None are skipped
- max_reclaim_per_run cap is respected
- primary_provider_reclaim_complete structlog event is emitted
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog.testing
from market_ingestion.domain.entities.ingestion_task import IngestionTask
from market_ingestion.domain.enums import DatasetType, IngestionTaskStatus, Provider
from market_ingestion.infrastructure.workers.reclaim_worker import PrimaryProviderReclaimWorker

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_routing_cache(primary_map: dict[tuple[str, str | None], str]) -> MagicMock:
    """Build a mock ProviderRoutingCache with a configurable primary_for() map.

    Args:
        primary_map: maps (dataset_type, timeframe) -> provider string.
    """
    cache = MagicMock()
    cache.primary_for = MagicMock(side_effect=lambda dt, tf: primary_map.get((dt, tf), "eodhd"))
    return cache


def _make_succeeded_task(
    *,
    fetched_by: str | None = "alpaca",
    dataset_type: DatasetType = DatasetType.OHLCV,
    timeframe: str | None = "1m",
    provider: Provider = Provider.EODHD,
    dedupe_key: str = "eodhd:ohlcv:AAPL:1m:abc123",
) -> IngestionTask:
    """Build a SUCCEEDED IngestionTask with the given fetched_by_provider."""
    return IngestionTask(
        id=f"task-{dedupe_key[-6:]}",
        provider=provider,
        dataset_type=dataset_type,
        symbol="AAPL",
        exchange="US",
        timeframe=timeframe,
        status=IngestionTaskStatus.SUCCEEDED,
        fetched_by_provider=fetched_by,
        dedupe_key=dedupe_key,
        created_at=datetime.now(tz=UTC),
    )


def _make_uow(tasks_list: list[IngestionTask] | None = None) -> MagicMock:
    """Build a mock UnitOfWork whose tasks repo returns *tasks_list*."""
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.tasks = MagicMock()
    uow.tasks.find_succeeded_with_fetched_by = AsyncMock(return_value=tasks_list or [])
    uow.tasks.add_many = AsyncMock(return_value=len(tasks_list or []))
    uow.commit = AsyncMock()
    return uow


# ===========================================================================
# Tests
# ===========================================================================


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_reclaim_identifies_secondary_tasks() -> None:
    """Tasks where fetched_by_provider != primary are identified for reclaim."""
    # Primary for ohlcv/1m is "alpaca", but the task was fetched by "polygon"
    routing_cache = _make_routing_cache({("ohlcv", "1m"): "alpaca"})
    task_polygon = _make_succeeded_task(fetched_by="polygon", dedupe_key="eodhd:ohlcv:AAPL:1m:001")
    task_alpaca = _make_succeeded_task(fetched_by="alpaca", dedupe_key="eodhd:ohlcv:AAPL:1m:002")

    uow = _make_uow([task_polygon, task_alpaca])

    worker = PrimaryProviderReclaimWorker(
        uow_factory=lambda: uow,
        routing_cache=routing_cache,
    )

    await worker._run_once()

    # add_many should have been called with exactly 1 reclaim task (polygon one)
    uow.tasks.add_many.assert_called_once()
    reclaim_tasks = uow.tasks.add_many.call_args[0][0]
    assert len(reclaim_tasks) == 1
    # The reclaim task targets the primary provider
    assert reclaim_tasks[0].provider == Provider.ALPACA


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_reclaim_creates_primary_tasks() -> None:
    """_make_reclaim_task() creates a task with the primary provider and same dedupe_key."""
    routing_cache = _make_routing_cache({("ohlcv", "1d"): "yahoo_finance"})

    worker = PrimaryProviderReclaimWorker(
        uow_factory=lambda: _make_uow(),
        routing_cache=routing_cache,
    )

    original = _make_succeeded_task(
        fetched_by="eodhd",
        dataset_type=DatasetType.OHLCV,
        timeframe="1d",
        dedupe_key="eodhd:ohlcv:AAPL:1d:xyz789",
    )

    reclaim = worker._make_reclaim_task(original)

    # Must target the primary provider (Yahoo Finance)
    assert reclaim.provider == Provider.YAHOO_FINANCE
    # Must share the same dedupe_key for ON CONFLICT DO NOTHING
    assert reclaim.dedupe_key == original.dedupe_key
    # Must have a different ID (fresh ULID)
    assert reclaim.id != original.id
    # Must preserve symbol, exchange, timeframe, dataset_type
    assert reclaim.symbol == original.symbol
    assert reclaim.exchange == original.exchange
    assert reclaim.timeframe == original.timeframe
    assert reclaim.dataset_type == original.dataset_type
    # Must be PENDING status
    assert reclaim.status == IngestionTaskStatus.PENDING


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_reclaim_idempotent_dedupe() -> None:
    """Same dedupe_key -> ON CONFLICT DO NOTHING; add_many returns 0 inserted."""
    routing_cache = _make_routing_cache({("ohlcv", "1m"): "alpaca"})
    task = _make_succeeded_task(fetched_by="polygon", dedupe_key="eodhd:ohlcv:AAPL:1m:dup01")

    uow = _make_uow([task])
    # Simulate ON CONFLICT DO NOTHING: add_many returns 0 (all conflicted)
    uow.tasks.add_many = AsyncMock(return_value=0)

    worker = PrimaryProviderReclaimWorker(
        uow_factory=lambda: uow,
        routing_cache=routing_cache,
    )

    await worker._run_once()

    # add_many was called but returned 0 — no new tasks inserted
    uow.tasks.add_many.assert_called_once()
    reclaim_tasks = uow.tasks.add_many.call_args[0][0]
    assert len(reclaim_tasks) == 1
    assert reclaim_tasks[0].dedupe_key == task.dedupe_key
    uow.commit.assert_called_once()


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_reclaim_skips_null_fetched_by() -> None:
    """Tasks with fetched_by_provider=None are not reclaimed."""
    routing_cache = _make_routing_cache({("ohlcv", "1m"): "alpaca"})
    task_null = _make_succeeded_task(fetched_by=None, dedupe_key="eodhd:ohlcv:AAPL:1m:null01")

    uow = _make_uow([task_null])

    worker = PrimaryProviderReclaimWorker(
        uow_factory=lambda: uow,
        routing_cache=routing_cache,
    )

    await worker._run_once()

    # No tasks to reclaim — add_many should NOT be called
    uow.tasks.add_many.assert_not_called()


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_reclaim_max_cap_5000() -> None:
    """When 6000 mismatched tasks exist, only 5000 reclaim tasks are created."""
    routing_cache = _make_routing_cache({("ohlcv", "1m"): "alpaca"})

    # Create 6000 tasks fetched by polygon (non-primary)
    candidates = [
        _make_succeeded_task(fetched_by="polygon", dedupe_key=f"eodhd:ohlcv:AAPL:1m:{i:06d}") for i in range(6000)
    ]
    uow = _make_uow(candidates)

    worker = PrimaryProviderReclaimWorker(
        uow_factory=lambda: uow,
        routing_cache=routing_cache,
        max_reclaim_per_run=5000,
    )

    await worker._run_once()

    # add_many called with at most 5000 tasks
    uow.tasks.add_many.assert_called_once()
    reclaim_tasks = uow.tasks.add_many.call_args[0][0]
    assert len(reclaim_tasks) == 5000


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_reclaim_logs_complete_event() -> None:
    """primary_provider_reclaim_complete structlog event is emitted."""
    routing_cache = _make_routing_cache({("ohlcv", "1m"): "alpaca"})
    task = _make_succeeded_task(fetched_by="polygon", dedupe_key="eodhd:ohlcv:AAPL:1m:log01")

    uow = _make_uow([task])
    uow.tasks.add_many = AsyncMock(return_value=1)

    worker = PrimaryProviderReclaimWorker(
        uow_factory=lambda: uow,
        routing_cache=routing_cache,
    )

    with structlog.testing.capture_logs() as cap_logs:
        await worker._run_once()

    # Find the primary_provider_reclaim_complete event
    reclaim_events = [e for e in cap_logs if e.get("event") == "primary_provider_reclaim_complete"]
    assert len(reclaim_events) == 1
    evt = reclaim_events[0]
    assert evt["reclaimed"] == 1
    assert evt["candidates"] == 1
    assert evt["filtered"] == 1
