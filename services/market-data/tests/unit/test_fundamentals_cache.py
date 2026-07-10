"""Unit tests for the fundamentals read-cache (chat-enhancement-roadmap Area 1 #3).

Covers: cache hit avoids a second DB call, distinct args miss independently,
TTL + key shape, cache-disabled path is a direct passthrough, and graceful
degradation when Valkey raises (get AND set) — the request must never fail.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from market_data.infrastructure.cache.fundamentals_cache import (
    CachedFundamentalsHistoryUseCase,
    CachedQueryFundamentalsUseCase,
    FundamentalsCache,
    _metrics_hash,
)

pytestmark = pytest.mark.unit


# ── Fakes ─────────────────────────────────────────────────────────────────────
class _FakeValkey:
    """In-memory stand-in for ValkeyClient with a call log."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.get_calls = 0
        self.set_calls = 0
        self.last_ttl: int | None = None

    async def get(self, key: str) -> str | None:
        self.get_calls += 1
        return self.store.get(key)

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        self.set_calls += 1
        self.last_ttl = ttl
        self.store[key] = value


def _history_inner(return_value: dict | None = None) -> MagicMock:
    inner = MagicMock()
    inner.execute = AsyncMock(
        return_value=return_value
        or {
            "periods": [{"period": "Q1 FY2026", "revenue": 100.0}],
            "period_count": 1,
            "current_snapshot": {"pe_ratio": 30.0, "as_of": date(2026, 3, 31)},
        }
    )
    return inner


def _query_inner(return_value: dict | None = None) -> MagicMock:
    inner = MagicMock()
    inner.execute = AsyncMock(
        return_value=return_value
        or {
            "metrics_by_period": [{"period_end": "2026-03-31", "revenue": 100.0}],
            "snapshot": {"forward_pe": 27.8},
            "coverage": {"revenue": "ok"},
        }
    )
    return inner


# ── Hit / miss behaviour ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_repeated_identical_query_hits_cache_no_second_db_call() -> None:
    """A second identical execute() serves from cache — inner use-case called once."""
    valkey = _FakeValkey()
    cache = FundamentalsCache(valkey, ttl=6 * 3600)
    inner = _history_inner()
    uc = CachedFundamentalsHistoryUseCase(inner, cache)
    iid = uuid4()

    first = await uc.execute(iid, periods=8, period_type="quarterly")
    second = await uc.execute(iid, periods=8, period_type="quarterly")

    # Same payload data (the only diff is date→ISO-string from the JSON round
    # trip on the hit path; the API schema re-parses both identically).
    assert first["period_count"] == second["period_count"] == 1
    assert first["periods"] == second["periods"]
    # DB (inner use-case) hit exactly once — the second call is a cache hit.
    inner.execute.assert_awaited_once()
    assert valkey.set_calls == 1


@pytest.mark.asyncio
async def test_different_args_miss_independently() -> None:
    """Different periods / period_type / metrics each produce their own miss."""
    valkey = _FakeValkey()
    cache = FundamentalsCache(valkey)
    inner = _history_inner()
    uc = CachedFundamentalsHistoryUseCase(inner, cache)
    iid = uuid4()

    await uc.execute(iid, periods=8, period_type="quarterly")
    await uc.execute(iid, periods=4, period_type="quarterly")  # different periods
    await uc.execute(iid, periods=8, period_type="annual")  # different period_type

    assert inner.execute.await_count == 3
    assert valkey.set_calls == 3


@pytest.mark.asyncio
async def test_query_metrics_order_independent_key() -> None:
    """Metric-set order does not fragment the cache (sorted hash)."""
    valkey = _FakeValkey()
    cache = FundamentalsCache(valkey)
    inner = _query_inner()
    uc = CachedQueryFundamentalsUseCase(inner, cache)
    iid = uuid4()

    await uc.execute(iid, ["revenue", "eps"], periods=8)
    await uc.execute(iid, ["eps", "revenue"], periods=8)  # same set, reversed

    inner.execute.assert_awaited_once()  # second is a hit
    assert _metrics_hash(["revenue", "eps"]) == _metrics_hash(["eps", "revenue"])


@pytest.mark.asyncio
async def test_query_include_snapshot_partitions_key() -> None:
    """include_snapshot changes the response shape → must be a distinct key."""
    valkey = _FakeValkey()
    cache = FundamentalsCache(valkey)
    inner = _query_inner()
    uc = CachedQueryFundamentalsUseCase(inner, cache)
    iid = uuid4()

    await uc.execute(iid, ["revenue"], include_snapshot=True)
    await uc.execute(iid, ["revenue"], include_snapshot=False)

    assert inner.execute.await_count == 2


# ── TTL / key shape ───────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ttl_is_respected_on_set() -> None:
    valkey = _FakeValkey()
    cache = FundamentalsCache(valkey, ttl=1234)
    uc = CachedFundamentalsHistoryUseCase(_history_inner(), cache)

    await uc.execute(uuid4(), periods=8, period_type="quarterly")
    assert valkey.last_ttl == 1234


def test_key_shape_and_normalisation() -> None:
    cache = FundamentalsCache(_FakeValkey())
    k = cache.key("history", "abc-123", periods=8, period_type="QUARTERLY")
    # period_type lower-cased; metrics/from/to rendered as placeholders.
    assert k == "md:v1:fund:history:abc-123:8:quarterly:-:-:-"


# ── Snapshot round-trip (date serialisation) ──────────────────────────────────
@pytest.mark.asyncio
async def test_snapshot_date_round_trips_through_json() -> None:
    """A date inside current_snapshot survives the JSON cache round-trip as ISO str."""
    valkey = _FakeValkey()
    cache = FundamentalsCache(valkey)
    uc = CachedFundamentalsHistoryUseCase(_history_inner(), cache)
    iid = uuid4()

    await uc.execute(iid, periods=8, period_type="quarterly")  # populate
    hit = await uc.execute(iid, periods=8, period_type="quarterly")  # from cache

    assert hit["current_snapshot"]["as_of"] == "2026-03-31"  # date → ISO string


# ── Graceful degradation ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_get_error_degrades_to_db() -> None:
    """A Valkey GET error falls through to the inner use-case (no raise)."""
    valkey = _FakeValkey()
    valkey.get = AsyncMock(side_effect=RuntimeError("valkey down"))  # type: ignore[method-assign]
    cache = FundamentalsCache(valkey)
    inner = _history_inner()
    uc = CachedFundamentalsHistoryUseCase(inner, cache)

    result = await uc.execute(uuid4(), periods=8, period_type="quarterly")

    assert result["period_count"] == 1  # DB path served the request
    inner.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_error_degrades_gracefully() -> None:
    """A Valkey SET error must not fail the request; result still returned."""
    valkey = _FakeValkey()
    valkey.set = AsyncMock(side_effect=RuntimeError("valkey down"))  # type: ignore[method-assign]
    cache = FundamentalsCache(valkey)
    inner = _history_inner()
    uc = CachedFundamentalsHistoryUseCase(inner, cache)

    result = await uc.execute(uuid4(), periods=8, period_type="quarterly")
    assert result["period_count"] == 1


@pytest.mark.asyncio
async def test_corrupt_cache_entry_treated_as_miss() -> None:
    """A non-JSON cached value degrades to a miss, not a 500."""
    valkey = _FakeValkey()
    cache = FundamentalsCache(valkey)
    key = cache.key("history", "iid", periods=8, period_type="quarterly")
    valkey.store[key] = "{not valid json"

    got = await cache.get(key, use_case="history")
    assert got is None


# ── Disabled path (dependency wiring) ─────────────────────────────────────────
def test_disabled_flag_returns_unwrapped_use_case() -> None:
    """With the flag off, the dependency returns the raw use-case (direct DB)."""
    from market_data.api.dependencies import get_fundamentals_history_uc
    from market_data.application.use_cases.get_fundamentals_history import (
        GetFundamentalsHistoryUseCase,
    )

    request = MagicMock()
    request.app.state.settings.fundamentals_cache_enabled = False
    request.app.state.valkey_client = _FakeValkey()

    uc = get_fundamentals_history_uc(request=request, uow=MagicMock())
    assert isinstance(uc, GetFundamentalsHistoryUseCase)


def test_enabled_flag_returns_cached_wrapper() -> None:
    """With the flag on and Valkey wired, the dependency returns the cached wrapper."""
    from market_data.api.dependencies import get_fundamentals_history_uc

    request = MagicMock()
    request.app.state.settings.fundamentals_cache_enabled = True
    request.app.state.settings.fundamentals_cache_ttl_seconds = 21_600
    request.app.state.valkey_client = _FakeValkey()

    uc = get_fundamentals_history_uc(request=request, uow=MagicMock())
    assert isinstance(uc, CachedFundamentalsHistoryUseCase)
