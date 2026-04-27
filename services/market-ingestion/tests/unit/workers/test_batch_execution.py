"""Unit tests for batch execution optimization in WorkerProcess.

Covers:
  1. Tasks with same (alpaca, 1m) are grouped together
  2. 10 tasks -> 1 HTTP call via fetch_ohlcv_batch
  3. Each symbol's bars are stored in its own bronze/canonical path
  4. EODHD tasks (supports_batch=False) -> individual execution
  5. Mixed Alpaca + EODHD tasks -> batch for Alpaca, individual for EODHD
  6. 1000 symbols -> exactly 1 HTTP call (within _BATCH_SIZE)
  7. 1001 symbols -> 2 HTTP calls (chunked by _BATCH_SIZE)
  8. 3000 symbols -> 3 HTTP calls
  9. One symbol with 0 bars doesn't block others
  10. Batch API error -> fall back to individual execution
  11. Base adapter supports_batch defaults to False
  12. Alpaca adapter supports_batch returns True
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from market_ingestion.application.ports.adapters import (
    ProviderAdapter,
    ProviderFetchResult,
)
from market_ingestion.domain.entities.ingestion_task import IngestionTask
from market_ingestion.domain.enums import (
    DatasetType,
    IngestionTaskStatus,
    Provider,
)
from market_ingestion.infrastructure.adapters.providers.alpaca import (
    AlpacaProviderAdapter,
)
from market_ingestion.infrastructure.adapters.providers.registry import (
    ProviderRegistry,
)
from market_ingestion.infrastructure.workers.worker import WorkerProcess
from pydantic import SecretStr

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_running_task(
    *,
    symbol: str = "AAPL",
    timeframe: str | None = "1m",
    dataset_type: DatasetType = DatasetType.OHLCV,
    provider: Provider = Provider.ALPACA,
    task_id: str | None = None,
) -> IngestionTask:
    """Build an IngestionTask in RUNNING state (as if just claimed)."""
    return IngestionTask(
        id=task_id or f"task-{symbol}-{timeframe}",
        provider=provider,
        dataset_type=dataset_type,
        symbol=symbol,
        exchange="US",
        timeframe=timeframe,
        status=IngestionTaskStatus.RUNNING,
        attempt_count=1,
        created_at=datetime.now(tz=UTC),
    )


def _make_fetch_result(
    symbol: str = "AAPL",
    bars_count: int = 3,
    provider: Provider = Provider.ALPACA,
) -> ProviderFetchResult:
    """Build a ProviderFetchResult with *bars_count* normalised bars."""
    bars = [
        {
            "timestamp": f"2024-01-0{i + 2}T14:30:00Z",
            "open": 100.0 + i,
            "high": 105.0 + i,
            "low": 95.0 + i,
            "close": 102.0 + i,
            "volume": 1000000 + i * 10000,
        }
        for i in range(bars_count)
    ]
    return ProviderFetchResult(
        provider=provider,
        dataset_type=DatasetType.OHLCV,
        symbol=symbol,
        raw_data=json.dumps(bars).encode(),
        content_type="application/json",
        fetched_at=datetime.now(tz=UTC),
        duration_ms=50,
        bars_returned=bars_count,
    )


def _make_batch_results(
    symbols: list[str],
    bars_per_symbol: int = 3,
) -> dict[str, ProviderFetchResult]:
    """Build a dict of symbol -> ProviderFetchResult for batch results."""
    return {sym: _make_fetch_result(symbol=sym, bars_count=bars_per_symbol) for sym in symbols}


def _make_alpaca_adapter_mock(*, supports_batch: bool = True) -> MagicMock:
    """Build a mock adapter that mimics AlpacaProviderAdapter."""
    adapter = MagicMock()
    adapter.provider = Provider.ALPACA
    adapter.supports_batch = supports_batch
    adapter.fetch_ohlcv_batch = AsyncMock(return_value={})
    adapter.fetch_intraday = AsyncMock()
    return adapter


def _make_eodhd_adapter_mock() -> MagicMock:
    """Build a mock adapter that mimics EODHD (no batch support)."""
    adapter = MagicMock()
    adapter.provider = Provider.EODHD
    adapter.supports_batch = False
    adapter.fetch_intraday = AsyncMock()
    return adapter


def _make_registry(*adapters: MagicMock) -> ProviderRegistry:
    """Build a ProviderRegistry with the given mock adapters."""
    registry = ProviderRegistry()
    for a in adapters:
        registry.register(a)
    return registry


def _make_mock_uow() -> MagicMock:
    """Build a mock UnitOfWork for Steps 2-5 processing in batch tests."""
    watermark = MagicMock(
        has_changed=MagicMock(return_value=True),
        current_bar_ts=None,
        advance_bar_ts=MagicMock(),
    )
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.tasks = MagicMock(save=AsyncMock())
    uow.watermarks = MagicMock(
        get_or_create=AsyncMock(return_value=watermark),
        get_for_update=AsyncMock(return_value=None),
        save=AsyncMock(),
    )
    uow.outbox = MagicMock(add=AsyncMock())
    uow.commit = AsyncMock()
    return uow


def _make_worker(
    registry: ProviderRegistry,
    routing_cache: Any | None = None,
) -> WorkerProcess:
    """Build a WorkerProcess with mocked infrastructure.

    Uses patch to bypass Settings construction and DB session factory builds.
    """
    settings = MagicMock()
    settings.bronze_bucket = "market-bronze"
    settings.canonical_bucket = "market-canonical"
    settings.storage_endpoint = "http://localhost:9000"
    settings.storage_access_key = SecretStr("test")
    settings.storage_secret_key = SecretStr("test")
    settings.storage_bucket = "test"
    settings.valkey_url = None

    factories = (MagicMock(), MagicMock())
    with (
        patch.object(WorkerProcess, "_build_registry", return_value=registry),
        patch.object(WorkerProcess, "_build_object_store", return_value=MagicMock()),
        patch.object(WorkerProcess, "_build_circuit_breaker", return_value=None),
        patch.object(WorkerProcess, "_build_zero_bar_tracker", return_value=None),
        patch.object(
            WorkerProcess,
            "_build_routing_cache",
            return_value=routing_cache,
        ),
        patch(
            "market_ingestion.infrastructure.workers.worker._build_factories",
            return_value=factories,
        ),
    ):
        worker = WorkerProcess(settings=settings, worker_id="test-worker")

    # Override object_store and serializer with mocks.
    worker._object_store = MagicMock()
    worker._object_store.exists = AsyncMock(return_value=False)
    worker._object_store.put = AsyncMock(
        return_value=MagicMock(
            sha256="abc123",
            byte_length=100,
            mime_type="application/x-ndjson",
        )
    )
    worker._serializer = MagicMock()
    worker._serializer.serialize_ohlcv = MagicMock(return_value=b'{"test":1}\n')

    return worker


def _make_routing_cache(
    primary_map: dict[tuple[str, str | None], str],
) -> MagicMock:
    """Build a mock ProviderRoutingCache."""
    cache = MagicMock()
    cache.primary_for = MagicMock(side_effect=lambda dt, tf: primary_map.get((dt, tf), "eodhd"))
    return cache


# ===========================================================================
# Test 1 — Tasks grouped by (provider, timeframe)
# ===========================================================================


@pytest.mark.asyncio
async def test_batch_groups_by_provider_timeframe() -> None:
    """Tasks with same (alpaca, 1m) grouped together for batch execution."""
    alpaca = _make_alpaca_adapter_mock()
    registry = _make_registry(alpaca)
    routing_cache = _make_routing_cache({("ohlcv", "1m"): "alpaca"})
    worker = _make_worker(registry, routing_cache)

    tasks = [
        _make_running_task(symbol="AAPL", timeframe="1m"),
        _make_running_task(symbol="MSFT", timeframe="1m"),
        _make_running_task(symbol="GOOG", timeframe="1m"),
    ]

    symbols = ["AAPL", "MSFT", "GOOG"]
    alpaca.fetch_ohlcv_batch.return_value = _make_batch_results(symbols)

    uow_patch = patch(
        "market_ingestion.infrastructure.workers.worker.SqlaUnitOfWork",
        return_value=_make_mock_uow(),
    )
    with uow_patch:
        batch_executed, remaining = await worker._try_batch_execute(tasks)

    assert len(batch_executed) == 3
    assert len(remaining) == 0

    # fetch_ohlcv_batch called exactly once with all 3 symbols.
    alpaca.fetch_ohlcv_batch.assert_called_once()
    call_kwargs = alpaca.fetch_ohlcv_batch.call_args
    assert sorted(call_kwargs.kwargs["symbols"]) == sorted(symbols)


# ===========================================================================
# Test 2 — 10 tasks -> 1 HTTP call via fetch_ohlcv_batch
# ===========================================================================


@pytest.mark.asyncio
async def test_batch_calls_fetch_ohlcv_batch_once() -> None:
    """10 Alpaca OHLCV/1m tasks produce exactly 1 batch API call."""
    alpaca = _make_alpaca_adapter_mock()
    registry = _make_registry(alpaca)
    routing_cache = _make_routing_cache({("ohlcv", "1m"): "alpaca"})
    worker = _make_worker(registry, routing_cache)

    symbols = [f"SYM{i:02d}" for i in range(10)]
    tasks = [_make_running_task(symbol=s, timeframe="1m") for s in symbols]
    alpaca.fetch_ohlcv_batch.return_value = _make_batch_results(symbols)

    uow_patch = patch(
        "market_ingestion.infrastructure.workers.worker.SqlaUnitOfWork",
        return_value=_make_mock_uow(),
    )
    with uow_patch:
        batch_executed, remaining = await worker._try_batch_execute(tasks)

    assert len(batch_executed) == 10
    assert len(remaining) == 0
    assert alpaca.fetch_ohlcv_batch.call_count == 1


# ===========================================================================
# Test 3 — Each symbol's bars stored in its own path
# ===========================================================================


@pytest.mark.asyncio
async def test_batch_distributes_results_per_symbol() -> None:
    """Each symbol's bars processed individually through Steps 2-5."""
    alpaca = _make_alpaca_adapter_mock()
    registry = _make_registry(alpaca)
    routing_cache = _make_routing_cache({("ohlcv", "1m"): "alpaca"})
    worker = _make_worker(registry, routing_cache)

    symbols = ["AAPL", "MSFT"]
    tasks = [_make_running_task(symbol=s, timeframe="1m") for s in symbols]
    alpaca.fetch_ohlcv_batch.return_value = _make_batch_results(symbols)

    uow_patch = patch(
        "market_ingestion.infrastructure.workers.worker.SqlaUnitOfWork",
    )
    with uow_patch as mock_uow_cls:
        mock_uow_cls.return_value = _make_mock_uow()
        batch_executed, remaining = await worker._try_batch_execute(tasks)

    assert len(batch_executed) == 2
    # SqlaUnitOfWork created once per symbol for Steps 2-5.
    assert mock_uow_cls.call_count == 2


# ===========================================================================
# Test 4 — Non-batch provider falls back to individual execution
# ===========================================================================


@pytest.mark.asyncio
async def test_non_batch_provider_falls_back_to_individual() -> None:
    """EODHD tasks (supports_batch=False) land in remaining list."""
    eodhd = _make_eodhd_adapter_mock()
    registry = _make_registry(eodhd)
    worker = _make_worker(registry, routing_cache=None)

    tasks = [
        _make_running_task(symbol="AAPL", timeframe="1m", provider=Provider.EODHD),
        _make_running_task(symbol="MSFT", timeframe="5m", provider=Provider.EODHD),
    ]

    batch_executed, remaining = await worker._try_batch_execute(tasks)

    assert len(batch_executed) == 0
    assert len(remaining) == 2
    eodhd.fetch_intraday.assert_not_called()


# ===========================================================================
# Test 5 — Mixed batch and individual
# ===========================================================================


@pytest.mark.asyncio
async def test_mixed_batch_and_individual() -> None:
    """5 Alpaca 1m + 5 EODHD 1d -> batch for Alpaca, individual for EODHD."""
    alpaca = _make_alpaca_adapter_mock()
    eodhd = _make_eodhd_adapter_mock()
    registry = _make_registry(alpaca, eodhd)
    routing_cache = _make_routing_cache({("ohlcv", "1m"): "alpaca", ("ohlcv", "1d"): "eodhd"})
    worker = _make_worker(registry, routing_cache)

    alpaca_symbols = [f"A{i}" for i in range(5)]
    alpaca_tasks = [_make_running_task(symbol=s, timeframe="1m") for s in alpaca_symbols]
    # EODHD 1d tasks — daily timeframe not in _INTRADAY_BATCH_TFS.
    eodhd_tasks = [_make_running_task(symbol=f"E{i}", timeframe="1d", provider=Provider.EODHD) for i in range(5)]

    all_tasks = alpaca_tasks + eodhd_tasks
    alpaca.fetch_ohlcv_batch.return_value = _make_batch_results(alpaca_symbols)

    uow_patch = patch(
        "market_ingestion.infrastructure.workers.worker.SqlaUnitOfWork",
        return_value=_make_mock_uow(),
    )
    with uow_patch:
        batch_executed, remaining = await worker._try_batch_execute(all_tasks)

    assert len(batch_executed) == 5
    assert len(remaining) == 5
    assert alpaca.fetch_ohlcv_batch.call_count == 1


# ===========================================================================
# Test 6 — 1000 symbols -> exactly 1 HTTP call
# ===========================================================================


@pytest.mark.asyncio
async def test_batch_1000_symbols() -> None:
    """1000 symbols within _BATCH_SIZE -> 1 HTTP call from the adapter."""
    alpaca = _make_alpaca_adapter_mock()
    registry = _make_registry(alpaca)
    routing_cache = _make_routing_cache({("ohlcv", "1m"): "alpaca"})
    worker = _make_worker(registry, routing_cache)

    symbols = [f"T{i:04d}" for i in range(1000)]
    tasks = [_make_running_task(symbol=s, timeframe="1m") for s in symbols]
    alpaca.fetch_ohlcv_batch.return_value = _make_batch_results(symbols, bars_per_symbol=1)

    uow_patch = patch(
        "market_ingestion.infrastructure.workers.worker.SqlaUnitOfWork",
        return_value=_make_mock_uow(),
    )
    with uow_patch:
        batch_executed, remaining = await worker._try_batch_execute(tasks)

    assert len(batch_executed) == 1000
    assert len(remaining) == 0
    assert alpaca.fetch_ohlcv_batch.call_count == 1


# ===========================================================================
# Test 7 — 1001 symbols -> adapter chunks into 2 HTTP calls
# ===========================================================================


@pytest.mark.asyncio
async def test_batch_1001_symbols() -> None:
    """1001 symbols -> adapter internally chunks into 2 HTTP calls.

    The worker itself calls fetch_ohlcv_batch once with all 1001 symbols;
    the adapter performs the chunking internally.
    """
    alpaca = _make_alpaca_adapter_mock()
    registry = _make_registry(alpaca)
    routing_cache = _make_routing_cache({("ohlcv", "1m"): "alpaca"})
    worker = _make_worker(registry, routing_cache)

    symbols = [f"T{i:04d}" for i in range(1001)]
    tasks = [_make_running_task(symbol=s, timeframe="1m") for s in symbols]
    alpaca.fetch_ohlcv_batch.return_value = _make_batch_results(symbols, bars_per_symbol=1)

    uow_patch = patch(
        "market_ingestion.infrastructure.workers.worker.SqlaUnitOfWork",
        return_value=_make_mock_uow(),
    )
    with uow_patch:
        batch_executed, remaining = await worker._try_batch_execute(tasks)

    assert len(batch_executed) == 1001
    assert len(remaining) == 0
    assert alpaca.fetch_ohlcv_batch.call_count == 1


# ===========================================================================
# Test 8 — 3000 symbols -> 1 worker call (adapter chunks into 3 HTTP calls)
# ===========================================================================


@pytest.mark.asyncio
async def test_batch_3000_symbols() -> None:
    """3000 symbols -> worker calls fetch_ohlcv_batch once."""
    alpaca = _make_alpaca_adapter_mock()
    registry = _make_registry(alpaca)
    routing_cache = _make_routing_cache({("ohlcv", "5m"): "alpaca"})
    worker = _make_worker(registry, routing_cache)

    symbols = [f"T{i:04d}" for i in range(3000)]
    tasks = [_make_running_task(symbol=s, timeframe="5m") for s in symbols]
    alpaca.fetch_ohlcv_batch.return_value = _make_batch_results(symbols, bars_per_symbol=1)

    uow_patch = patch(
        "market_ingestion.infrastructure.workers.worker.SqlaUnitOfWork",
        return_value=_make_mock_uow(),
    )
    with uow_patch:
        batch_executed, remaining = await worker._try_batch_execute(tasks)

    assert len(batch_executed) == 3000
    assert len(remaining) == 0
    assert alpaca.fetch_ohlcv_batch.call_count == 1


# ===========================================================================
# Test 9 — Failed symbol doesn't block others
# ===========================================================================


@pytest.mark.asyncio
async def test_batch_failed_symbol_doesnt_block_others() -> None:
    """If one symbol returns 0 bars, the other symbols still succeed."""
    alpaca = _make_alpaca_adapter_mock()
    registry = _make_registry(alpaca)
    routing_cache = _make_routing_cache({("ohlcv", "1m"): "alpaca"})
    worker = _make_worker(registry, routing_cache)

    results = {
        "AAPL": _make_fetch_result("AAPL", bars_count=3),
        "BAD_SYM": _make_fetch_result("BAD_SYM", bars_count=0),
    }
    alpaca.fetch_ohlcv_batch.return_value = results

    tasks = [
        _make_running_task(symbol="AAPL", timeframe="1m"),
        _make_running_task(symbol="BAD_SYM", timeframe="1m"),
    ]

    uow_patch = patch(
        "market_ingestion.infrastructure.workers.worker.SqlaUnitOfWork",
        return_value=_make_mock_uow(),
    )
    with uow_patch:
        batch_executed, remaining = await worker._try_batch_execute(tasks)

    assert len(batch_executed) == 2
    assert len(remaining) == 0


# ===========================================================================
# Test 10 — Batch API error retries individually
# ===========================================================================


@pytest.mark.asyncio
async def test_batch_api_error_retries_individually() -> None:
    """If batch API call fails, tasks fall back to individual execution."""
    alpaca = _make_alpaca_adapter_mock()
    alpaca.fetch_ohlcv_batch.side_effect = Exception("Alpaca API timeout")
    registry = _make_registry(alpaca)
    routing_cache = _make_routing_cache({("ohlcv", "1m"): "alpaca"})
    worker = _make_worker(registry, routing_cache)

    tasks = [
        _make_running_task(symbol="AAPL", timeframe="1m"),
        _make_running_task(symbol="MSFT", timeframe="1m"),
    ]

    batch_executed, remaining = await worker._try_batch_execute(tasks)

    assert len(batch_executed) == 0
    assert len(remaining) == 2
    alpaca.fetch_ohlcv_batch.assert_called_once()


# ===========================================================================
# Test 11 — supports_batch default is False
# ===========================================================================


def test_supports_batch_default_false() -> None:
    """Base ProviderAdapter.supports_batch defaults to False."""

    class _DummyAdapter(ProviderAdapter):
        @property
        def provider(self) -> Provider:
            return Provider.EODHD

        async def fetch_quotes(self, symbol, exchange=None): ...  # pragma: no cover

        async def fetch_ohlcv(self, symbol, timeframe, start, end, exchange=None): ...  # pragma: no cover

        async def fetch_fundamentals(self, symbol, variant, exchange=None): ...  # pragma: no cover

    adapter = _DummyAdapter()
    assert adapter.supports_batch is False


# ===========================================================================
# Test 12 — Alpaca supports_batch is True
# ===========================================================================


def test_alpaca_supports_batch_true() -> None:
    """AlpacaProviderAdapter.supports_batch returns True."""
    adapter = AlpacaProviderAdapter(
        api_key=SecretStr("test-key"),
        secret_key=SecretStr("test-secret"),
        client=MagicMock(),
    )
    assert adapter.supports_batch is True
