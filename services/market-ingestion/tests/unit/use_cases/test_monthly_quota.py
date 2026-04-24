"""Unit tests for EodhdQuotaService monthly credit quota enforcement.

Tests verify:
- Atomic increment via Valkey
- Hard-limit block without incrementing
- Soft-limit warning while still allowing the call
- Monthly key isolation (different months → different keys)
- Service attribution keys
- Symbol attribution keys
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from messaging.eodhd_quota.quota_service import (
    EodhdQuotaService,
    QuotaCheckResult,
    QuotaStatus,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_valkey(initial_value: int = 0) -> MagicMock:
    """Return a mock ValkeyClient whose get() returns *initial_value*."""
    valkey = MagicMock()
    # get() → initial value as string (or None if 0, simulating key not yet created)
    valkey.get = AsyncMock(return_value=str(initial_value) if initial_value else None)
    # incr() → initial_value + increment (default +1)
    valkey.incr = AsyncMock(side_effect=lambda key, amount=1: initial_value + amount)
    valkey.expire = AsyncMock(return_value=True)
    return valkey


def _make_service(
    valkey: MagicMock | None = None,
    initial_value: int = 0,
    hard_limit: int = 100_000,
    soft_limit_ratio: float = 0.80,
) -> tuple[EodhdQuotaService, MagicMock]:
    if valkey is None:
        valkey = _make_valkey(initial_value)
    service = EodhdQuotaService(
        valkey=valkey,
        hard_limit=hard_limit,
        soft_limit_ratio=soft_limit_ratio,
    )
    return service, valkey


# ---------------------------------------------------------------------------
# try_consume — quota increment logic
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_monthly_quota_increments_atomically() -> None:
    """Credits are incremented via Valkey INCRBY (atomic) and OK returned."""
    service, valkey = _make_service(initial_value=0)
    # Simulate fresh month: get returns None, incr returns 1
    valkey.get = AsyncMock(return_value=None)
    valkey.incr = AsyncMock(return_value=1)

    result = await service.try_consume(cost=1, service="market-ingestion", symbol="AAPL")

    assert result == QuotaCheckResult.OK
    valkey.incr.assert_called()
    # TTL must be set on total key
    valkey.expire.assert_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_monthly_quota_rejects_when_hard_limit_reached() -> None:
    """When current credits >= hard_limit, return HARD_LIMIT_EXCEEDED without incrementing."""
    service, valkey = _make_service(initial_value=100_000)
    # Current value is exactly at hard limit
    valkey.get = AsyncMock(return_value="100000")

    result = await service.try_consume(cost=1, service="market-ingestion")

    assert result == QuotaCheckResult.HARD_LIMIT_EXCEEDED
    # Must NOT increment when already at hard limit
    valkey.incr.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_monthly_quota_rejects_when_hard_limit_exceeded() -> None:
    """When current credits > hard_limit (concurrent race), HARD_LIMIT_EXCEEDED returned."""
    service, valkey = _make_service(initial_value=0)
    # Simulate race: get returned 0, but after INCRBY the new total exceeds limit
    valkey.get = AsyncMock(return_value="99999")
    valkey.incr = AsyncMock(return_value=100_001)  # over hard limit after increment

    result = await service.try_consume(cost=2, service="market-ingestion")

    assert result == QuotaCheckResult.HARD_LIMIT_EXCEEDED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_monthly_quota_soft_limit_triggers_warning() -> None:
    """When credits reach soft limit (80%), return SOFT_LIMIT_EXCEEDED (allowed)."""
    service, valkey = _make_service(initial_value=0)
    # After increment, new total = 80_001 → above soft limit (80_000)
    valkey.get = AsyncMock(return_value="79_999")
    valkey.incr = AsyncMock(return_value=80_001)

    result = await service.try_consume(cost=2, service="market-ingestion")

    # Soft limit → warning but NOT blocked
    assert result == QuotaCheckResult.SOFT_LIMIT_EXCEEDED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_monthly_quota_returns_ok_below_soft_limit() -> None:
    """Normal consumption below soft limit returns OK."""
    service, valkey = _make_service(initial_value=0)
    valkey.get = AsyncMock(return_value="1000")
    valkey.incr = AsyncMock(return_value=1010)

    result = await service.try_consume(cost=10, service="market-ingestion")

    assert result == QuotaCheckResult.OK


@pytest.mark.unit
@pytest.mark.asyncio
async def test_monthly_quota_service_attribution() -> None:
    """Service attribution key is incremented alongside total key."""
    service, valkey = _make_service(initial_value=0)
    valkey.get = AsyncMock(return_value=None)
    valkey.incr = AsyncMock(return_value=5)

    month = "2026-04"
    await service.try_consume(cost=5, service="s2", month=month)

    # Both total key and service key should be incremented
    incr_calls = [call.args[0] for call in valkey.incr.call_args_list]
    total_key = f"eodhd:v1:quota:{month}:credits_used"
    service_key = f"eodhd:v1:quota:{month}:s2:credits_used"
    assert total_key in incr_calls
    assert service_key in incr_calls


@pytest.mark.unit
@pytest.mark.asyncio
async def test_monthly_quota_symbol_attribution() -> None:
    """Symbol attribution key is written when symbol is provided."""
    service, valkey = _make_service(initial_value=0)
    valkey.get = AsyncMock(return_value=None)
    valkey.incr = AsyncMock(return_value=1)

    month = "2026-04"
    await service.try_consume(cost=1, service="s2", symbol="AAPL", month=month)

    incr_calls = [call.args[0] for call in valkey.incr.call_args_list]
    sym_key = f"eodhd:v1:quota:{month}:symbol:AAPL:credits_used"
    assert sym_key in incr_calls


@pytest.mark.unit
@pytest.mark.asyncio
async def test_monthly_quota_no_symbol_attribution_when_symbol_absent() -> None:
    """No symbol attribution key written when symbol=None."""
    service, valkey = _make_service(initial_value=0)
    valkey.get = AsyncMock(return_value=None)
    valkey.incr = AsyncMock(return_value=1)

    month = "2026-04"
    await service.try_consume(cost=1, service="s2", symbol=None, month=month)

    incr_calls = [call.args[0] for call in valkey.incr.call_args_list]
    assert not any("symbol" in k for k in incr_calls)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_monthly_quota_month_key_isolation() -> None:
    """Using an explicit month parameter writes to month-specific keys only."""
    service, valkey = _make_service(initial_value=0)
    valkey.get = AsyncMock(return_value=None)
    valkey.incr = AsyncMock(return_value=1)

    await service.try_consume(cost=1, service="s2", month="2026-03")

    incr_calls = [call.args[0] for call in valkey.incr.call_args_list]
    assert all("2026-03" in k for k in incr_calls)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_monthly_quota_ttl_set_on_increment() -> None:
    """A 32-day TTL is set on both total and service keys after increment."""
    service, valkey = _make_service(initial_value=0)
    valkey.get = AsyncMock(return_value=None)
    valkey.incr = AsyncMock(return_value=1)

    await service.try_consume(cost=1, service="s2", month="2026-04")

    expire_calls = valkey.expire.call_args_list
    # At least 2 calls: total key + service key
    assert len(expire_calls) >= 2
    # All TTLs should be 32 days (32 * 86400)
    assert all(call.args[1] == 32 * 86_400 for call in expire_calls)


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_status_returns_correct_values() -> None:
    """get_status() returns the current usage from Valkey."""
    service, valkey = _make_service()
    valkey.get = AsyncMock(return_value="42000")

    status = await service.get_status(month="2026-04")

    assert isinstance(status, QuotaStatus)
    assert status.credits_used == 42_000
    assert status.hard_limit == 100_000
    assert status.soft_limit == 80_000
    assert status.month == "2026-04"
    assert status.percent_used == pytest.approx(42.0)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_status_returns_zero_when_key_absent() -> None:
    """get_status() returns 0 credits when no Valkey key exists yet."""
    service, valkey = _make_service()
    valkey.get = AsyncMock(return_value=None)

    status = await service.get_status(month="2026-04")

    assert status.credits_used == 0
    assert status.percent_used == 0.0
