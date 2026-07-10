"""Unit tests for PLAN-0056 Wave B3 config: provider poll cadence + backfill env vars."""

from __future__ import annotations

import pytest
from content_ingestion.config import (
    PolymarketClobProviderSettings,
    PolymarketEventsProviderSettings,
    PolymarketOIProviderSettings,
    PolymarketTradesProviderSettings,
    Settings,
)

pytestmark = pytest.mark.unit


class TestPollCadenceDefaults:
    """PRD-0033 §4.2 cadences: events 1h, CLOB 6h, trades 1h, OI daily."""

    def test_events_hourly(self) -> None:
        assert PolymarketEventsProviderSettings().poll_interval_seconds == 3600.0

    def test_clob_six_hourly(self) -> None:
        assert PolymarketClobProviderSettings().poll_interval_seconds == 21600.0

    def test_trades_hourly(self) -> None:
        assert PolymarketTradesProviderSettings().poll_interval_seconds == 3600.0

    def test_oi_daily(self) -> None:
        assert PolymarketOIProviderSettings().poll_interval_seconds == 86400.0


class TestBackfillEnvVars:
    def test_history_backfill_days_default(self) -> None:
        assert Settings().polymarket_history_backfill_days == 14

    def test_trades_backfill_days_default(self) -> None:
        assert Settings().polymarket_trades_backfill_days == 14
