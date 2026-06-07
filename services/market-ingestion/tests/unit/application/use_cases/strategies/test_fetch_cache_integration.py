"""Integration tests for the MarketDataCache wiring in ``fetch_for_task``.

PLAN-0107 A-3 follow-up
-----------------------
The cache wiring lives in
``market_ingestion.application.use_cases.strategies.fetch.fetch_for_task`` and
funnels three dataset branches (EOD OHLCV, FUNDAMENTALS, EARNINGS_CALENDAR)
through :class:`MarketDataCache.get_or_fetch`. These tests pin the wiring at
the use-case boundary so a future refactor cannot silently drop the cache:

1. Hit path: cache returns a stored envelope -> adapter is NOT called.
2. Miss path: cache.get_or_fetch invokes the fetcher and stores the payload
   with the EOD-OHLCV TTL (21600s).
3. Key shape: FUNDAMENTALS routes through the ``fundamentals_snapshot`` key.

The tests use a small ``_FakeCache`` instead of mocking ``get_or_fetch`` itself
so the call contract (positional vs kwargs, fetcher invocation, TTL lookup) is
exercised end-to-end without spinning up Valkey.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from market_ingestion.application.ports.adapters import ProviderFetchResult
from market_ingestion.application.use_cases.strategies.fetch import (
    _encode_fetch_result,
    fetch_for_task,
)
from market_ingestion.domain.entities.ingestion_task import IngestionTask
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.infrastructure.cache.cache_policy import (
    CACHE_TTL_SECONDS,
)
from market_ingestion.infrastructure.cache.cache_policy import (
    DatasetType as CacheDatasetType,
)

# ---------------------------------------------------------------------------
# Fakes & fixtures
# ---------------------------------------------------------------------------


class _FakeCache:
    """Minimal stand-in for :class:`MarketDataCache`.

    Mirrors the real ``get_or_fetch`` contract: returns a pre-seeded payload on
    hit, otherwise awaits the fetcher and records a ``(key, ttl)`` set call so
    tests can pin the TTL without instantiating Valkey.
    """

    def __init__(self, hits: dict[tuple[CacheDatasetType, str, str], dict[str, Any]] | None = None) -> None:
        self._hits = hits or {}
        self.get_or_fetch_calls: list[dict[str, Any]] = []
        self.set_calls: list[tuple[str, int]] = []  # (key, ttl)

    async def get_or_fetch(
        self,
        dataset_type: CacheDatasetType,
        symbol: str,
        period_key: str,
        fetcher: Any,
        *,
        provider_label: str,
    ) -> dict[str, Any]:
        # Record every call so tests can assert key composition.
        self.get_or_fetch_calls.append(
            {
                "dataset_type": dataset_type,
                "symbol": symbol,
                "period_key": period_key,
                "provider_label": provider_label,
            }
        )
        cache_key = f"market_data:{dataset_type.value}:{symbol.lower()}:{period_key}"
        hit = self._hits.get((dataset_type, symbol, period_key))
        if hit is not None:
            return hit
        payload = await fetcher()
        self.set_calls.append((cache_key, CACHE_TTL_SECONDS[dataset_type]))
        return payload


def _make_fetch_result(
    *,
    symbol: str = "AAPL",
    dataset_type: DatasetType = DatasetType.OHLCV,
    raw: bytes = b"{}",
) -> ProviderFetchResult:
    """Build a minimal ``ProviderFetchResult`` for round-trip envelope tests."""
    return ProviderFetchResult(
        provider=Provider.EODHD,
        dataset_type=dataset_type,
        symbol=symbol,
        raw_data=raw,
        content_type="application/json",
        fetched_at=datetime.now(tz=UTC),
        duration_ms=42,
        bars_returned=1,
    )


def _ohlcv_eod_task() -> IngestionTask:
    return IngestionTask(
        dataset_type=DatasetType.OHLCV,
        symbol="AAPL",
        timeframe="1d",
        range_start=datetime(2026, 1, 1, tzinfo=UTC),
        range_end=datetime(2026, 1, 31, tzinfo=UTC),
    )


def _fundamentals_task() -> IngestionTask:
    return IngestionTask(
        dataset_type=DatasetType.FUNDAMENTALS,
        symbol="MSFT",
        variant="annual",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ohlcv_eod_hit_skips_adapter() -> None:
    """Cache hit short-circuits the adapter call and returns the decoded payload."""
    task = _ohlcv_eod_task()
    period_key = f"1d:{task.range_start.isoformat()}:{task.range_end.isoformat()}"  # type: ignore[union-attr]

    cached_result = _make_fetch_result(symbol="AAPL", raw=b'{"cached":true}')
    cache = _FakeCache(
        hits={(CacheDatasetType.OHLCV_EOD, "AAPL", period_key): _encode_fetch_result(cached_result)},
    )

    adapter = AsyncMock()
    adapter.provider = Provider.EODHD
    adapter.fetch_ohlcv = AsyncMock()

    result = await fetch_for_task(adapter, task, cache=cache)  # type: ignore[arg-type]

    adapter.fetch_ohlcv.assert_not_called()
    assert result.raw_data == b'{"cached":true}'
    assert cache.set_calls == []  # nothing written on hit
    assert cache.get_or_fetch_calls[0]["dataset_type"] == CacheDatasetType.OHLCV_EOD


@pytest.mark.asyncio
async def test_ohlcv_eod_miss_calls_adapter_and_stores() -> None:
    """Cache miss -> adapter invoked exactly once and result stored with TTL=21600."""
    task = _ohlcv_eod_task()
    fetched = _make_fetch_result(symbol="AAPL", raw=b'{"fresh":true}')

    cache = _FakeCache()
    adapter = AsyncMock()
    adapter.provider = Provider.EODHD
    adapter.fetch_ohlcv = AsyncMock(return_value=fetched)

    result = await fetch_for_task(adapter, task, cache=cache)  # type: ignore[arg-type]

    adapter.fetch_ohlcv.assert_awaited_once()
    assert result.raw_data == b'{"fresh":true}'
    assert len(cache.set_calls) == 1
    stored_key, stored_ttl = cache.set_calls[0]
    assert stored_ttl == 21_600  # CACHE_TTL_SECONDS[OHLCV_EOD]
    assert stored_key.startswith("market_data:ohlcv_eod:aapl:1d:")


@pytest.mark.asyncio
async def test_fundamentals_uses_correct_dataset_key() -> None:
    """FUNDAMENTALS branch routes through the ``fundamentals_snapshot`` cache key."""
    task = _fundamentals_task()
    fetched = _make_fetch_result(symbol="MSFT", dataset_type=DatasetType.FUNDAMENTALS, raw=b'{"f":1}')

    cache = _FakeCache()
    adapter = AsyncMock()
    adapter.provider = Provider.EODHD
    adapter.fetch_fundamentals = AsyncMock(return_value=fetched)

    await fetch_for_task(adapter, task, cache=cache)  # type: ignore[arg-type]

    adapter.fetch_fundamentals.assert_awaited_once()
    call = cache.get_or_fetch_calls[0]
    assert call["dataset_type"] is CacheDatasetType.FUNDAMENTALS_SNAPSHOT
    assert call["symbol"] == "MSFT"
    assert call["period_key"] == "latest"
    # Verify the materialised cache key contains the dataset slug.
    stored_key, stored_ttl = cache.set_calls[0]
    assert "fundamentals_snapshot" in stored_key
    assert stored_ttl == CACHE_TTL_SECONDS[CacheDatasetType.FUNDAMENTALS_SNAPSHOT]
