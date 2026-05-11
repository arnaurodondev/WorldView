"""Tests for _default_chunk_days_for_timeframe + _MAX_CHUNKS bump (PLAN-0055 A-1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from market_ingestion.application.use_cases.backfill import (
    _MAX_CHUNKS,
    BackfillUseCase,
    _default_chunk_days_for_timeframe,
)

pytestmark = pytest.mark.unit


class TestDefaultChunkDaysForTimeframe:
    def test_daily_returns_year(self) -> None:
        assert _default_chunk_days_for_timeframe("1d") == 365

    def test_weekly_returns_year(self) -> None:
        assert _default_chunk_days_for_timeframe("1w") == 365

    def test_monthly_returns_year(self) -> None:
        assert _default_chunk_days_for_timeframe("1mo") == 365
        assert _default_chunk_days_for_timeframe("1M") == 365

    def test_intraday_returns_thirty(self) -> None:
        assert _default_chunk_days_for_timeframe("5m") == 30
        assert _default_chunk_days_for_timeframe("1m") == 30
        assert _default_chunk_days_for_timeframe("1h") == 30
        assert _default_chunk_days_for_timeframe("4h") == 30

    def test_unknown_timeframe_falls_to_intraday(self) -> None:
        # Defensive: any timeframe not in the daily-or-coarser set is treated as intraday.
        assert _default_chunk_days_for_timeframe("garbage") == 30


class TestMaxChunksBump:
    def test_max_chunks_is_five_hundred(self) -> None:
        # PLAN-0055 A-1 bumped 100 → 500 to support 10y daily horizons in one call.
        assert _MAX_CHUNKS == 500

    def test_split_chunks_within_cap(self) -> None:
        # 10 years of daily ÷ 365 chunk_days = ~10 chunks, well under 500.
        start = datetime(2016, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 1, tzinfo=UTC)
        chunks = BackfillUseCase._split_chunks(start, end, chunk_days=365)
        assert len(chunks) <= _MAX_CHUNKS

    def test_split_chunks_at_cap_with_small_chunk_days(self) -> None:
        # 500 days x 1-day chunks = 500 chunks (exactly at cap).
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = start + timedelta(days=500)
        chunks = BackfillUseCase._split_chunks(start, end, chunk_days=1)
        assert len(chunks) == 500
