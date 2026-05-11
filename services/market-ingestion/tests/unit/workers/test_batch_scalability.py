"""Scalability validation tests for batch execution optimization.

Verifies that batch execution reduces API calls by the expected factor
across different ticker counts.

Covers:
  1.  64 tickers -> 1 batch API call
  2. 100 tickers -> 1 batch API call
  3. 500 tickers -> 1 batch API call
  4. 1000 tickers -> 1 batch API call (at limit)
  5. 3000 tickers -> 1 batch call from worker (3 HTTP inside adapter)
  6. 100 individual calls -> 1 batch call = 100x reduction
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from market_ingestion.application.ports.adapters import ProviderFetchResult
from market_ingestion.domain.entities.ingestion_task import IngestionTask
from market_ingestion.domain.enums import (
    DatasetType,
    IngestionTaskStatus,
    Provider,
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


def _running_task(symbol: str, timeframe: str = "1m") -> IngestionTask:
    """Build a RUNNING OHLCV task for the given symbol."""
    return IngestionTask(
        id=f"task-{symbol}",
        provider=Provider.ALPACA,
        dataset_type=DatasetType.OHLCV,
        symbol=symbol,
        exchange="US",
        timeframe=timeframe,
        status=IngestionTaskStatus.RUNNING,
        attempt_count=1,
        created_at=datetime.now(tz=UTC),
    )


def _fetch_result(symbol: str) -> ProviderFetchResult:
    """Minimal ProviderFetchResult with 1 bar for the symbol."""
    bar = json.dumps(
        [
            {
                "timestamp": "2024-01-02T14:30:00Z",
                "open": 100.0,
                "high": 105.0,
                "low": 95.0,
                "close": 102.0,
                "volume": 1000000,
            }
        ]
    ).encode()
    return ProviderFetchResult(
        provider=Provider.ALPACA,
        dataset_type=DatasetType.OHLCV,
        symbol=symbol,
        raw_data=bar,
        content_type="application/json",
        fetched_at=datetime.now(tz=UTC),
        duration_ms=10,
        bars_returned=1,
    )


def _batch_results(
    symbols: list[str],
) -> dict[str, ProviderFetchResult]:
    """Build batch results for a list of symbols."""
    return {s: _fetch_result(s) for s in symbols}


def _mock_uow() -> MagicMock:
    """Build a mock UoW for Steps 2-5 processing."""
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


def _make_alpaca() -> MagicMock:
    """Build a mock Alpaca adapter with supports_batch=True."""
    adapter = MagicMock()
    adapter.provider = Provider.ALPACA
    adapter.supports_batch = True
    adapter.fetch_ohlcv_batch = AsyncMock()
    return adapter


def _routing_alpaca_1m() -> MagicMock:
    """Routing cache that routes all ohlcv to alpaca."""
    cache = MagicMock()
    cache.primary_for = MagicMock(side_effect=lambda dt, tf: "alpaca" if dt == "ohlcv" else "eodhd")
    return cache


def _build_worker(
    alpaca_mock: MagicMock,
    routing_cache: MagicMock,
) -> WorkerProcess:
    """Build a WorkerProcess with mocked infra for scalability tests."""
    registry = ProviderRegistry()
    registry.register(alpaca_mock)

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
        worker = WorkerProcess(settings=settings, worker_id="scale-test-worker")

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


# ===========================================================================
# Scalability tests
# ===========================================================================


@pytest.mark.asyncio
async def test_batch_64_tickers_1_call() -> None:
    """64 tickers -> 1 batch API call, all results distributed."""
    n = 64
    symbols = [f"T{i:04d}" for i in range(n)]
    alpaca = _make_alpaca()
    alpaca.fetch_ohlcv_batch.return_value = _batch_results(symbols)
    worker = _build_worker(alpaca, _routing_alpaca_1m())

    tasks = [_running_task(s) for s in symbols]

    uow_patch = patch(
        "market_ingestion.infrastructure.workers.worker.SqlaUnitOfWork",
        return_value=_mock_uow(),
    )
    with uow_patch:
        batch_executed, remaining = await worker._try_batch_execute(tasks)

    assert len(batch_executed) == n
    assert len(remaining) == 0
    assert alpaca.fetch_ohlcv_batch.call_count == 1


@pytest.mark.asyncio
async def test_batch_100_tickers_1_call() -> None:
    """100 tickers -> 1 batch API call."""
    n = 100
    symbols = [f"T{i:04d}" for i in range(n)]
    alpaca = _make_alpaca()
    alpaca.fetch_ohlcv_batch.return_value = _batch_results(symbols)
    worker = _build_worker(alpaca, _routing_alpaca_1m())

    tasks = [_running_task(s) for s in symbols]

    uow_patch = patch(
        "market_ingestion.infrastructure.workers.worker.SqlaUnitOfWork",
        return_value=_mock_uow(),
    )
    with uow_patch:
        batch_executed, remaining = await worker._try_batch_execute(tasks)

    assert len(batch_executed) == n
    assert len(remaining) == 0
    assert alpaca.fetch_ohlcv_batch.call_count == 1


@pytest.mark.asyncio
async def test_batch_500_tickers_1_call() -> None:
    """500 tickers -> 1 batch API call."""
    n = 500
    symbols = [f"T{i:04d}" for i in range(n)]
    alpaca = _make_alpaca()
    alpaca.fetch_ohlcv_batch.return_value = _batch_results(symbols)
    worker = _build_worker(alpaca, _routing_alpaca_1m())

    tasks = [_running_task(s) for s in symbols]

    uow_patch = patch(
        "market_ingestion.infrastructure.workers.worker.SqlaUnitOfWork",
        return_value=_mock_uow(),
    )
    with uow_patch:
        batch_executed, remaining = await worker._try_batch_execute(tasks)

    assert len(batch_executed) == n
    assert len(remaining) == 0
    assert alpaca.fetch_ohlcv_batch.call_count == 1


@pytest.mark.asyncio
async def test_batch_1000_tickers_1_call() -> None:
    """1000 tickers -> 1 batch API call (at Alpaca _BATCH_SIZE limit)."""
    n = 1000
    symbols = [f"T{i:04d}" for i in range(n)]
    alpaca = _make_alpaca()
    alpaca.fetch_ohlcv_batch.return_value = _batch_results(symbols)
    worker = _build_worker(alpaca, _routing_alpaca_1m())

    tasks = [_running_task(s) for s in symbols]

    uow_patch = patch(
        "market_ingestion.infrastructure.workers.worker.SqlaUnitOfWork",
        return_value=_mock_uow(),
    )
    with uow_patch:
        batch_executed, remaining = await worker._try_batch_execute(tasks)

    assert len(batch_executed) == n
    assert len(remaining) == 0
    assert alpaca.fetch_ohlcv_batch.call_count == 1


@pytest.mark.asyncio
async def test_batch_3000_tickers_3_calls() -> None:
    """3000 tickers -> adapter internally chunks into 3 HTTP calls.

    This test uses the real AlpacaProviderAdapter.fetch_ohlcv_batch
    to verify that chunking produces exactly 3 HTTP calls.
    """
    from market_ingestion.infrastructure.adapters.providers.alpaca import (
        AlpacaProviderAdapter,
    )

    n = 3000
    symbols = [f"T{i:04d}" for i in range(n)]

    empty_resp = json.dumps({"bars": {}, "next_page_token": None}).encode()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = empty_resp
    mock_response.headers = {}

    client = MagicMock()
    client.get = AsyncMock(return_value=mock_response)

    adapter = AlpacaProviderAdapter(
        api_key=SecretStr("test-key"),
        secret_key=SecretStr("test-secret"),
        client=client,
    )

    results = await adapter.fetch_ohlcv_batch(
        symbols=symbols,
        timeframe="1m",
        start=None,
        end=None,
    )

    assert len(results) == n
    # Exactly 3 HTTP calls (3000 / 1000 = 3 chunks).
    assert client.get.call_count == 3


@pytest.mark.asyncio
async def test_batch_reduces_api_calls_by_factor() -> None:
    """100 individual -> 1 batch call = 100x reduction.

    Verifies the core value proposition: batch execution reduces API
    call count by a factor equal to the number of symbols in the batch.
    """
    n = 100
    symbols = [f"T{i:04d}" for i in range(n)]
    alpaca = _make_alpaca()
    alpaca.fetch_ohlcv_batch.return_value = _batch_results(symbols)
    worker = _build_worker(alpaca, _routing_alpaca_1m())

    tasks = [_running_task(s) for s in symbols]

    uow_patch = patch(
        "market_ingestion.infrastructure.workers.worker.SqlaUnitOfWork",
        return_value=_mock_uow(),
    )
    with uow_patch:
        batch_executed, remaining = await worker._try_batch_execute(tasks)

    # Without batching: n individual fetch calls.
    individual_api_calls = n
    # With batching: 1 batch call.
    batch_api_calls = alpaca.fetch_ohlcv_batch.call_count
    assert batch_api_calls == 1

    reduction_factor = individual_api_calls / batch_api_calls
    assert reduction_factor == n  # 100x reduction
    assert len(batch_executed) == n
    assert len(remaining) == 0
