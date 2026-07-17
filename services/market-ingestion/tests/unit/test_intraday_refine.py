"""Unit tests for the once-daily post-close EODHD 1m intraday refinement.

Covers the pure, I/O-free helpers (day resolution, weekend guard, UTC-day window,
resume-set key, credit budget, source re-stamping) plus the end-to-end
canonicalization of an EODHD ``/intraday`` record — proving a produced 1m bar
carries the CORRECT consolidated volume, a UTC bar-start ``date`` that ALIGNS with
Alpaca's 1m convention, and the authoritative ``eodhd_intraday`` source (which S3
resolves to priority 115 — above Alpaca's IEX 1m at 110).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from market_ingestion.application.ports.adapters import ProviderFetchResult
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.scripts.intraday_refine import (
    _CREDITS_PER_SYMBOL,
    _DEFAULT_SETTLE_LAG_DAYS,
    RunBudget,
    day_date_range,
    day_unix_window,
    done_set_key,
    is_weekend,
    pick_probe_symbol,
    preflight_day_published,
    resolve_target_day,
    stamp_intraday_source,
)

import common.time

pytestmark = pytest.mark.unit


def _bars_result(n_bars: int) -> ProviderFetchResult:
    """A ProviderFetchResult carrying *n_bars* intraday records (n=0 => unpublished/holiday)."""
    records = [dict(_BAR_1330) for _ in range(n_bars)]
    return ProviderFetchResult(
        provider=Provider.EODHD,
        dataset_type=DatasetType.OHLCV,
        symbol="AAPL",
        raw_data=json.dumps(records).encode(),
        content_type="application/json",
        fetched_at=datetime.now(tz=UTC),
        duration_ms=1,
        bars_returned=n_bars,
    )


class _FakeAdapter:
    """Minimal async adapter double that counts fetch_intraday calls."""

    def __init__(self, n_bars: int, *, raise_error: bool = False) -> None:
        self._n = n_bars
        self._raise = raise_error
        self.calls = 0

    async def fetch_intraday(self, **_kwargs: object) -> ProviderFetchResult:
        self.calls += 1
        if self._raise:
            raise RuntimeError("boom")
        return _bars_result(self._n)


# A live-verified EODHD /intraday 1m record shape (UTC bar-start, consolidated vol).
# 2026-07-15 13:30:00 UTC = 09:30 ET regular-session open.
_BAR_1330 = {
    "timestamp": 1752586200,
    "gmtoffset": 0,
    "datetime": "2026-07-15 13:30:00",
    "open": 100.0,
    "high": 101.0,
    "low": 99.5,
    "close": 100.5,
    "volume": 3_930_530,
}


# ── resolve_target_day ────────────────────────────────────────────────────────


def test_resolve_target_day_explicit_is_utc_midnight_no_lag():
    # An explicit --date is used verbatim — the settle-lag must NOT apply.
    day = resolve_target_day("2026-07-15", settle_lag_days=2)
    assert day == datetime(2026, 7, 15, tzinfo=UTC)


def test_default_settle_lag_is_two_trading_days():
    # Grounded in the live probe (2026-07-17): at Fri 01:22 UTC the just-closed
    # Thursday (T-1) had 0 intraday bars while Wednesday (T-2) was complete.
    assert _DEFAULT_SETTLE_LAG_DAYS == 2


def test_resolve_target_day_default_applies_trading_day_lag(monkeypatch):
    # Freeze "now" to Friday 2026-07-17 23:30 UTC (the CronJob slot).
    monkeypatch.setattr(common.time, "utc_now", lambda: datetime(2026, 7, 17, 23, 30, tzinfo=UTC))
    # Default lag=2 trading days → Wednesday 2026-07-15 (the reliably-settled day).
    assert resolve_target_day(None).date() == datetime(2026, 7, 15, tzinfo=UTC).date()
    # lag=1 → Thursday 2026-07-16.
    assert resolve_target_day(None, settle_lag_days=1).date() == datetime(2026, 7, 16, tzinfo=UTC).date()
    # lag=0 → today.
    assert resolve_target_day(None, settle_lag_days=0).date() == datetime(2026, 7, 17, tzinfo=UTC).date()


def test_resolve_target_day_lag_skips_weekends(monkeypatch):
    # Monday 2026-07-20 23:30 UTC: lag=1 trading day must skip Sun/Sat back to Friday.
    monkeypatch.setattr(common.time, "utc_now", lambda: datetime(2026, 7, 20, 23, 30, tzinfo=UTC))
    assert resolve_target_day(None, settle_lag_days=1).date() == datetime(2026, 7, 17, tzinfo=UTC).date()
    # lag=2 → Thursday 2026-07-16.
    assert resolve_target_day(None, settle_lag_days=2).date() == datetime(2026, 7, 16, tzinfo=UTC).date()


def test_resolve_target_day_default_lands_on_a_weekday(monkeypatch):
    # Whatever "today" is, the lagged default is always a trading weekday.
    monkeypatch.setattr(common.time, "utc_now", lambda: datetime(2026, 7, 19, 23, 30, tzinfo=UTC))  # Sunday
    assert not is_weekend(resolve_target_day(None))


def test_resolve_target_day_bad_format_raises():
    with pytest.raises(ValueError):
        resolve_target_day("07/15/2026")


# ── is_weekend ────────────────────────────────────────────────────────────────


def test_is_weekend_true_for_saturday_sunday():
    assert is_weekend(resolve_target_day("2026-07-18"))  # Saturday
    assert is_weekend(resolve_target_day("2026-07-19"))  # Sunday


def test_is_weekend_false_for_weekday():
    assert not is_weekend(resolve_target_day("2026-07-15"))  # Wednesday


# ── day_unix_window / day_date_range ──────────────────────────────────────────


def test_day_unix_window_covers_full_utc_calendar_day():
    from_ts, to_ts = day_unix_window(resolve_target_day("2026-07-15"))
    assert from_ts == int(datetime(2026, 7, 15, tzinfo=UTC).timestamp())
    assert to_ts == int(datetime(2026, 7, 16, tzinfo=UTC).timestamp())
    # 24h window bracketing pre-market, regular, and after-hours (all in UTC).
    assert (to_ts - from_ts) == 24 * 60 * 60


def test_day_date_range_single_day_window():
    dr = day_date_range(resolve_target_day("2026-07-15"))
    assert dr.start == datetime(2026, 7, 15, tzinfo=UTC)
    assert dr.end == datetime(2026, 7, 16, tzinfo=UTC)


# ── done_set_key ──────────────────────────────────────────────────────────────


def test_done_set_key_is_per_day_and_versioned():
    assert done_set_key(resolve_target_day("2026-07-15")) == "s2:v1:intraday_refine:2026-07-15:done"


# ── stamp_intraday_source ─────────────────────────────────────────────────────


def test_stamp_intraday_source_overrides_provider_only():
    raw = ProviderFetchResult(
        provider=Provider.EODHD,  # adapter default
        dataset_type=DatasetType.OHLCV,
        symbol="AAPL",
        raw_data=json.dumps([_BAR_1330]).encode(),
        content_type="application/json",
        fetched_at=datetime.now(tz=UTC),
        duration_ms=7,
        bars_returned=1,
    )
    stamped = stamp_intraday_source(raw)
    # Only the source identity flips — everything else is preserved verbatim.
    assert stamped.provider is Provider.EODHD_INTRADAY
    assert stamped.raw_data == raw.raw_data
    assert stamped.bars_returned == 1
    assert raw.provider is Provider.EODHD  # original untouched (pure)


# ── RunBudget ─────────────────────────────────────────────────────────────────


def test_credits_per_symbol_is_five():
    # EODHD /intraday costs 5 credits/request regardless of interval.
    assert _CREDITS_PER_SYMBOL == 5


def test_run_budget_enforces_both_ceilings():
    budget = RunBudget(max_credits=12, daily_cap=100_000, daily_headroom=5_000)
    assert not budget.run_budget_exhausted(5)
    budget.record_symbol()  # +5
    budget.record_symbol()  # +10
    assert budget.spent == 10
    # A third symbol (+5 → 15) would exceed the 12 per-run cap.
    assert budget.run_budget_exhausted(5)
    # Daily headroom: 100_000 - 5_000 = 95_000 usable.
    assert budget.daily_budget_exhausted(daily_used=94_996, next_estimate=5)
    assert not budget.daily_budget_exhausted(daily_used=90_000, next_estimate=5)


def test_full_us_sweep_credit_estimate_fits_daily_cap():
    # 530 covered US equities x 5 credits = 2,650/sweep — plus daily bulk EOD
    # (~543) + the existing firehose (~1.1k) is ~4.3k, well under the 100k/day cap.
    assert 530 * _CREDITS_PER_SYMBOL == 2_650
    assert 2_650 + 543 + 1_100 < 100_000


# ── pick_probe_symbol ─────────────────────────────────────────────────────────


def test_pick_probe_symbol_prefers_liquid_reference():
    # A liquid always-trading ticker makes "0 bars" reliably mean "day unpublished".
    assert pick_probe_symbol(["ZZZ", "MSFT", "AAA"]) == "MSFT"


def test_pick_probe_symbol_falls_back_to_first_sorted():
    assert pick_probe_symbol(["ZZZ", "AAA", "MMM"]) == "AAA"


def test_pick_probe_symbol_empty_universe_is_none():
    assert pick_probe_symbol([]) is None


# ── preflight_day_published (the credit-burn guard) ───────────────────────────


@pytest.mark.asyncio
async def test_preflight_published_day_returns_result_one_call():
    # A liquid probe with bars ⇒ day is published; the result is returned for reuse
    # (so the probe's credit is not wasted) and exactly ONE API call was made.
    adapter = _FakeAdapter(n_bars=960)
    published, result = await preflight_day_published(adapter, "AAPL", "US", 0, 86_400)
    assert published is True
    assert result is not None and result.bars_returned == 960
    assert adapter.calls == 1


@pytest.mark.asyncio
async def test_preflight_unpublished_day_aborts_without_second_call():
    # 0 bars from the liquid probe ⇒ day not yet published ⇒ abort. This is the
    # guard that stops the ~2,650-credit burn: only the single probe call happens,
    # and the caller writes NO done-set entries (verified structurally: preflight
    # returns (False, None) BEFORE the sweep loop that would fetch/mark symbols).
    adapter = _FakeAdapter(n_bars=0)
    published, result = await preflight_day_published(adapter, "AAPL", "US", 0, 86_400)
    assert published is False
    assert result is None
    assert adapter.calls == 1


@pytest.mark.asyncio
async def test_preflight_fetch_error_treated_as_unpublished():
    # A network error can't confirm publication ⇒ treat as not-published (abort,
    # no done-set poisoning) rather than risk spending the full budget.
    adapter = _FakeAdapter(n_bars=0, raise_error=True)
    published, result = await preflight_day_published(adapter, "AAPL", "US", 0, 86_400)
    assert published is False
    assert result is None
    assert adapter.calls == 1


# ── end-to-end canonicalization ───────────────────────────────────────────────


def test_produced_1m_bar_canonicalizes_with_consolidated_volume_and_aligned_ts():
    # The same canonicalizer the live worker uses must emit a 1m bar whose volume
    # is the consolidated CTA/UTP figure (not IEX), whose ``date`` is the UTC
    # bar-start minute (aligns with Alpaca's 1m bar_date so the S3 upsert guard
    # REPLACES the IEX bar), and whose source is the authoritative eodhd_intraday.
    from market_ingestion.application.use_cases.strategies.canonicalize import canonicalize_task
    from market_ingestion.domain.entities.ingestion_task import IngestionTask
    from market_ingestion.domain.value_objects import Timeframe
    from market_ingestion.infrastructure.adapters.canonical import DefaultCanonicalSerializer

    dr = day_date_range(resolve_target_day("2026-07-15"))
    raw = ProviderFetchResult(
        provider=Provider.EODHD,
        dataset_type=DatasetType.OHLCV,
        symbol="AAPL",
        raw_data=json.dumps([_BAR_1330]).encode(),
        content_type="application/json",
        fetched_at=datetime.now(tz=UTC),
        duration_ms=7,
        bars_returned=1,
    )
    fetch_result = stamp_intraday_source(raw)
    task = IngestionTask.create_ohlcv_task(
        provider=Provider.EODHD_INTRADAY,
        symbol="AAPL",
        timeframe=Timeframe("1m"),
        date_range=dr,
        exchange="US",
    )
    canonical_bytes, row_count = canonicalize_task(task, fetch_result, DefaultCanonicalSerializer())
    assert row_count == 1
    bar = json.loads(canonical_bytes.decode().splitlines()[0])
    assert bar["symbol"] == "AAPL"
    assert bar["volume"] == 3_930_530  # consolidated, NOT the ~5% IEX figure
    assert bar["source"] == "eodhd_intraday"  # → provider_priority 115 in market-data
    # UTC bar-start minute — the exact-minute alignment that makes it collide with
    # (and supersede) the Alpaca IEX 1m bar rather than duplicate it.
    assert bar["date"].startswith("2026-07-15T13:30:00")
