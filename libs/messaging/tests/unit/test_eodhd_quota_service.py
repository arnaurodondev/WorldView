"""Unit tests for EodhdQuotaService — cross-replica monthly + daily counters.

Covers:
  * try_consume increments the monthly total + per-service + per-symbol + daily
    counters by the credit cost,
  * the hard-limit pre-check blocks once the monthly total is at/over the cap,
  * soft-limit signalling,
  * get_daily_credits_used reads the cumulative per-UTC-day counter.

Valkey is mocked with a simple in-memory dict so counter arithmetic is real.
"""

from __future__ import annotations

import pytest

from messaging.eodhd_quota.quota_service import (
    EodhdQuotaService,
    QuotaCheckResult,
)

pytestmark = pytest.mark.unit


class _FakeValkey:
    """Minimal in-memory Valkey double implementing get / incr / expire."""

    def __init__(self) -> None:
        self.store: dict[str, int] = {}
        self.expires: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        val = self.store.get(key)
        return str(val) if val is not None else None

    async def incr(self, key: str, amount: int = 1) -> int:
        self.store[key] = self.store.get(key, 0) + amount
        return self.store[key]

    async def expire(self, key: str, seconds: int) -> bool:
        self.expires[key] = seconds
        return True


@pytest.mark.unit
async def test_try_consume_increments_all_counters() -> None:
    vk = _FakeValkey()
    svc = EodhdQuotaService(valkey=vk, hard_limit=100_000)

    result = await svc.try_consume(cost=10, service="market-ingestion", symbol="AAPL", month="2026-06")

    assert result == QuotaCheckResult.OK
    assert vk.store["eodhd:v1:quota:2026-06:credits_used"] == 10
    assert vk.store["eodhd:v1:quota:2026-06:market-ingestion:credits_used"] == 10
    assert vk.store["eodhd:v1:quota:2026-06:symbol:AAPL:credits_used"] == 10
    # The new cumulative per-UTC-day counter must also be incremented.
    day_keys = [k for k in vk.store if k.startswith("eodhd:v1:quota:day:")]
    assert len(day_keys) == 1
    assert vk.store[day_keys[0]] == 10


@pytest.mark.unit
async def test_try_consume_counts_fundamentals_cost() -> None:
    """A 10-credit fundamentals fetch adds exactly 10 to the daily counter."""
    vk = _FakeValkey()
    svc = EodhdQuotaService(valkey=vk, hard_limit=100_000)

    await svc.try_consume(cost=10, service="market-ingestion", month="2026-06")
    await svc.try_consume(cost=1, service="market-ingestion", month="2026-06")

    daily = await svc.get_daily_credits_used()
    assert daily == 11


@pytest.mark.unit
async def test_hard_limit_blocks_when_at_cap() -> None:
    vk = _FakeValkey()
    svc = EodhdQuotaService(valkey=vk, hard_limit=100)
    # Pre-seed the monthly total at the cap.
    month_key = "eodhd:v1:quota:2026-06:credits_used"
    vk.store[month_key] = 100

    result = await svc.try_consume(cost=5, service="market-ingestion", month="2026-06")

    assert result == QuotaCheckResult.HARD_LIMIT_EXCEEDED
    # Blocked call must NOT consume additional credits.
    assert vk.store[month_key] == 100
    # And must not have created a daily counter for this blocked call.
    assert not [k for k in vk.store if k.startswith("eodhd:v1:quota:day:")]


@pytest.mark.unit
async def test_soft_limit_signalled_but_not_blocked() -> None:
    vk = _FakeValkey()
    svc = EodhdQuotaService(valkey=vk, hard_limit=100, soft_limit_ratio=0.80)
    vk.store["eodhd:v1:quota:2026-06:credits_used"] = 75

    result = await svc.try_consume(cost=10, service="market-ingestion", month="2026-06")

    # 75 + 10 = 85 ≥ soft (80) but < hard (100).
    assert result == QuotaCheckResult.SOFT_LIMIT_EXCEEDED
    assert vk.store["eodhd:v1:quota:2026-06:credits_used"] == 85


@pytest.mark.unit
async def test_get_daily_credits_used_zero_when_empty() -> None:
    vk = _FakeValkey()
    svc = EodhdQuotaService(valkey=vk)

    assert await svc.get_daily_credits_used(day="2026-06-16") == 0


@pytest.mark.unit
async def test_get_daily_credits_used_reads_counter() -> None:
    vk = _FakeValkey()
    svc = EodhdQuotaService(valkey=vk)
    vk.store["eodhd:v1:quota:day:2026-06-16:credits_used"] = 4242

    assert await svc.get_daily_credits_used(day="2026-06-16") == 4242


@pytest.mark.unit
async def test_record_usage_increments_shared_counters() -> None:
    """record_usage rolls a caller's spend into the SAME shared counters.

    Regression guard for the S4 blind spot: content-ingestion's EODHD spend must
    land on ``eodhd:v1:quota:{month}:credits_used`` (the cross-service total), not
    a divergent key, so the account-wide monthly figure is a true rollup.
    """
    vk = _FakeValkey()
    svc = EodhdQuotaService(valkey=vk, hard_limit=100_000)

    result = await svc.record_usage(cost=5, service="content-ingestion", symbol="AAPL.US", month="2026-06")

    assert result == QuotaCheckResult.OK
    assert vk.store["eodhd:v1:quota:2026-06:credits_used"] == 5
    assert vk.store["eodhd:v1:quota:2026-06:content-ingestion:credits_used"] == 5
    assert vk.store["eodhd:v1:quota:2026-06:symbol:AAPL.US:credits_used"] == 5


@pytest.mark.unit
async def test_record_usage_best_effort_swallows_valkey_failure() -> None:
    """A Valkey failure must NEVER propagate out of record_usage."""

    class _BrokenValkey(_FakeValkey):
        async def incr(self, key: str, amount: int = 1) -> int:
            raise RuntimeError("valkey down")

    svc = EodhdQuotaService(valkey=_BrokenValkey(), hard_limit=100_000)

    # Must not raise — returns None to signal the counter was not written.
    result = await svc.record_usage(cost=5, service="content-ingestion", month="2026-06")

    assert result is None


@pytest.mark.unit
async def test_record_usage_returns_soft_limit_for_alerting() -> None:
    """record_usage surfaces the threshold result so callers can alert loudly."""
    vk = _FakeValkey()
    svc = EodhdQuotaService(valkey=vk, hard_limit=100, soft_limit_ratio=0.80)
    vk.store["eodhd:v1:quota:2026-06:credits_used"] = 78

    result = await svc.record_usage(cost=5, service="content-ingestion", month="2026-06")

    # 78 + 5 = 83 ≥ soft (80) but < hard (100).
    assert result == QuotaCheckResult.SOFT_LIMIT_EXCEEDED
