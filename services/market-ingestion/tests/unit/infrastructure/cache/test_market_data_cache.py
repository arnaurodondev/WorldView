"""Tests for :class:`MarketDataCache` (PLAN-0107 A-2).

Covers the six required scenarios from the plan:

(a) hit path -- Valkey returns serialised payload; fetcher is never called.
(b) miss-then-fill -- Valkey returns ``None``; fetcher is called once; the
    result is JSON-serialised + stored with the correct TTL.
(c) Valkey GET raises -- fetcher is still called; cache error is swallowed.
(d) Valkey SET raises -- fetcher result is still returned successfully.
(e) Inflight sentinel -- ``set_nx`` returns ``False``; we sleep + retry GET
    once, then fall through to the fetcher.
(f) Key-format snapshot -- exact key string for one canonical combo.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from market_ingestion.infrastructure.cache.cache_policy import (
    CACHE_TTL_SECONDS,
    DatasetType,
)
from market_ingestion.infrastructure.cache.market_data_cache import (
    MarketDataCache,
    _build_key,
)


def _make_valkey(*, get_return: Any = None, set_nx_return: bool = True) -> AsyncMock:
    """Return an ``AsyncMock`` that mimics the subset of ValkeyClient we touch."""
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=get_return)
    mock.set = AsyncMock(return_value=None)
    mock.set_nx = AsyncMock(return_value=set_nx_return)
    return mock


# -- (a) hit path ------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_fetch_returns_cached_payload_without_calling_fetcher() -> None:
    payload = {"bars": [1, 2, 3], "symbol": "AAPL"}
    valkey = _make_valkey(get_return=json.dumps(payload, sort_keys=True, separators=(",", ":")))
    cache = MarketDataCache(valkey)

    fetcher = AsyncMock()  # MUST NOT be called

    result = await cache.get_or_fetch(
        DatasetType.OHLCV_EOD,
        "AAPL",
        "1d:2024-01-01:2024-12-31",
        fetcher,
        provider_label="eodhd",
    )

    assert result == payload
    fetcher.assert_not_called()
    valkey.set.assert_not_called()  # No fill on hit.
    valkey.set_nx.assert_not_called()  # No inflight claim on hit.


# -- (b) miss-then-fill ------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_fetch_calls_fetcher_on_miss_and_stores_result() -> None:
    valkey = _make_valkey(get_return=None, set_nx_return=True)
    cache = MarketDataCache(valkey)

    payload = {"snapshot": {"pe": 28.5}, "currency": "USD"}
    fetcher = AsyncMock(return_value=payload)

    result = await cache.get_or_fetch(
        DatasetType.FUNDAMENTALS_SNAPSHOT,
        "AAPL",
        "latest",
        fetcher,
        provider_label="eodhd",
    )

    assert result == payload
    fetcher.assert_awaited_once_with()

    # Stored with the correct key, canonical JSON, and the policy TTL.
    expected_key = "market_data:fundamentals_snapshot:aapl:latest"
    expected_value = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    expected_ttl = CACHE_TTL_SECONDS[DatasetType.FUNDAMENTALS_SNAPSHOT]
    valkey.set.assert_awaited_once_with(expected_key, expected_value, ex=expected_ttl)


# -- (c) Valkey GET raises ---------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_fetch_falls_through_when_valkey_get_raises() -> None:
    valkey = _make_valkey(set_nx_return=True)
    valkey.get = AsyncMock(side_effect=ConnectionError("valkey down"))
    cache = MarketDataCache(valkey)

    payload = {"earnings": []}
    fetcher = AsyncMock(return_value=payload)

    result = await cache.get_or_fetch(
        DatasetType.EARNINGS_CALENDAR,
        "MSFT",
        "2024-Q1",
        fetcher,
        provider_label="eodhd",
    )

    assert result == payload
    fetcher.assert_awaited_once_with()


# -- (d) Valkey SET raises ---------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_fetch_returns_payload_when_valkey_set_raises() -> None:
    valkey = _make_valkey(get_return=None, set_nx_return=True)
    valkey.set = AsyncMock(side_effect=ConnectionError("valkey down"))
    cache = MarketDataCache(valkey)

    payload = {"divs": []}
    fetcher = AsyncMock(return_value=payload)

    result = await cache.get_or_fetch(
        DatasetType.DIVIDENDS,
        "AAPL",
        "2024",
        fetcher,
        provider_label="eodhd",
    )

    # SET failure must not propagate.
    assert result == payload
    fetcher.assert_awaited_once_with()


# -- (e) Inflight sentinel ---------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_fetch_inflight_retries_then_falls_through_to_fetcher() -> None:
    """When ``set_nx`` returns ``False`` another worker is already fetching.

    The cache must sleep a jittered window, retry GET exactly once, and -- if
    that retry is still a miss -- fall through to the fetcher itself.
    """
    valkey = _make_valkey(get_return=None, set_nx_return=False)
    cache = MarketDataCache(valkey)

    payload = {"splits": []}
    fetcher = AsyncMock(return_value=payload)

    result = await cache.get_or_fetch(
        DatasetType.SPLITS,
        "GOOG",
        "2024",
        fetcher,
        provider_label="eodhd",
    )

    assert result == payload
    # GET should be called twice: once initially, once after the inflight wait.
    assert valkey.get.await_count == 2
    valkey.set_nx.assert_awaited_once()
    fetcher.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_get_or_fetch_inflight_retry_hit_skips_fetcher() -> None:
    """If the sibling worker's fill lands during our jittered sleep, the
    retried GET must short-circuit and we MUST NOT call the fetcher ourselves.
    """
    payload = {"exchanges": ["NASDAQ"]}
    serialised = json.dumps(payload, sort_keys=True, separators=(",", ":"))

    valkey = _make_valkey(set_nx_return=False)
    # First GET -> miss, second GET -> hit (sibling filled while we slept).
    valkey.get = AsyncMock(side_effect=[None, serialised])
    cache = MarketDataCache(valkey)

    fetcher = AsyncMock()

    result = await cache.get_or_fetch(
        DatasetType.EXCHANGES_LIST,
        "",
        "all",
        fetcher,
        provider_label="eodhd",
    )

    assert result == payload
    fetcher.assert_not_called()


# -- (f) Key-format snapshot -------------------------------------------------


def test_build_key_matches_documented_format() -> None:
    """Snapshot test for the exact wire-format key.

    Guards against accidental schema drift (PLAN-0107 section A.5). Any change
    to this string is a cache-invalidation event and demands a migration step.
    """
    key = _build_key(DatasetType.OHLCV_EOD, "AAPL", "1d:2024-01-01:2024-12-31")
    assert key == "market_data:ohlcv_eod:aapl:1d:2024-01-01:2024-12-31"


# -- Bonus: validation guard -------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_fetch_rejects_non_enum_dataset_type() -> None:
    cache = MarketDataCache(_make_valkey())
    fetcher = AsyncMock()
    with pytest.raises(ValueError, match="dataset_type"):
        await cache.get_or_fetch(
            "quote_realtime",  # type: ignore[arg-type]
            "AAPL",
            "now",
            fetcher,
            provider_label="eodhd",
        )
    fetcher.assert_not_called()
