"""Unit tests for ProviderRoutingCache — config-backed provider routing."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from market_ingestion.application.services.provider_routing_cache import ProviderRoutingCache

pytestmark = pytest.mark.unit


def _make_settings(**overrides: str) -> MagicMock:
    """Build a mock Settings with default routing config fields.

    Defaults mirror the production defaults in ``config.py``.
    Pass keyword arguments to override any routing field.
    """
    defaults = {
        "routing_ohlcv_intraday": "alpaca:100,polygon:80",
        "routing_ohlcv_eod": "alpaca:100,eodhd:80",
        "routing_quotes": "eodhd:100",
        "routing_fundamentals": "eodhd:100",
        "routing_news_sentiment": "finnhub:100,eodhd:80",
        "routing_earnings_calendar": "finnhub:100,eodhd:80",
        "routing_insider_transactions": "finnhub:100,eodhd:80",
    }
    defaults.update(overrides)
    mock = MagicMock()
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


# ------------------------------------------------------------------
# T-A-3-01 tests
# ------------------------------------------------------------------


@pytest.mark.unit
class TestProviderRoutingCache:
    """Tests for ProviderRoutingCache application service."""

    def test_cache_primary_for_returns_highest_weight(self) -> None:
        """Highest-weight provider is returned first by primary_for()."""
        cache = ProviderRoutingCache()
        settings = _make_settings(routing_ohlcv_intraday="polygon:50,alpaca:100")
        cache.load_from_config(settings)

        # alpaca has weight 100, polygon has weight 50 → alpaca first
        assert cache.primary_for("ohlcv", "1m") == "alpaca"
        assert cache.primary_for("ohlcv", "5m") == "alpaca"

    def test_cache_fallback_eodhd_when_no_rules(self) -> None:
        """Missing slot falls back to ["eodhd"]."""
        cache = ProviderRoutingCache()
        settings = _make_settings()
        cache.load_from_config(settings)

        # "unknown_dataset" was never configured
        assert cache.get_providers_for("unknown_dataset", None) == ["eodhd"]
        assert cache.primary_for("unknown_dataset", "1m") == "eodhd"

    def test_cache_load_from_config_intraday(self) -> None:
        """routing_ohlcv_intraday='alpaca:100,polygon:80' → alpaca first for ohlcv/1m."""
        cache = ProviderRoutingCache()
        settings = _make_settings(routing_ohlcv_intraday="alpaca:100,polygon:80")
        cache.load_from_config(settings)

        providers = cache.get_providers_for("ohlcv", "1m")
        assert providers == ["alpaca", "polygon"]
        assert cache.primary_for("ohlcv", "1m") == "alpaca"

        # All intraday timeframes should have the same providers
        for tf in ("1m", "5m", "15m", "30m", "1h", "4h"):
            assert cache.get_providers_for("ohlcv", tf) == ["alpaca", "polygon"]

    def test_cache_load_from_config_eod(self) -> None:
        """routing_ohlcv_eod='alpaca:100,eodhd:80' → Alpaca primary, EODHD failover for ohlcv/1d.

        PLAN-0036 final topology: Alpaca is the deep-daily primary; Yahoo is dropped.
        """
        cache = ProviderRoutingCache()
        settings = _make_settings(routing_ohlcv_eod="alpaca:100,eodhd:80")
        cache.load_from_config(settings)

        providers = cache.get_providers_for("ohlcv", "1d")
        assert providers == ["alpaca", "eodhd"]
        assert cache.primary_for("ohlcv", "1d") == "alpaca"
        # Yahoo must be absent from EOD routing entirely.
        assert "yahoo_finance" not in providers

        # All EOD timeframes should have the same providers
        for tf in ("1d", "1w", "1M"):
            assert cache.get_providers_for("ohlcv", tf) == ["alpaca", "eodhd"]

    def test_cache_load_from_config_invalid_pair(self) -> None:
        """Malformed pair is skipped; valid entries still loaded."""
        cache = ProviderRoutingCache()
        # "bad_entry" has no ":weight" separator → skipped
        # "alpaca:abc" has non-integer weight → skipped
        # "polygon:90" is valid → kept
        settings = _make_settings(
            routing_ohlcv_intraday="bad_entry,alpaca:abc,polygon:90",
        )
        cache.load_from_config(settings)

        providers = cache.get_providers_for("ohlcv", "1m")
        assert providers == ["polygon"]

    def test_cache_load_from_config_resets_stale(self) -> None:
        """Second load_from_config() call replaces all previous entries."""
        cache = ProviderRoutingCache()

        # First load — alpaca:100 for intraday
        settings_v1 = _make_settings(routing_ohlcv_intraday="alpaca:100")
        cache.load_from_config(settings_v1)
        assert cache.primary_for("ohlcv", "1m") == "alpaca"

        # Second load — polygon:100 for intraday (replaces alpaca)
        settings_v2 = _make_settings(routing_ohlcv_intraday="polygon:100")
        cache.load_from_config(settings_v2)
        assert cache.primary_for("ohlcv", "1m") == "polygon"

        # Verify alpaca is gone — providers list should only contain polygon
        providers = cache.get_providers_for("ohlcv", "1m")
        assert "alpaca" not in providers

    def test_loaded_at_iso_before_load(self) -> None:
        """Before any load, loaded_at_iso() returns 'never'."""
        cache = ProviderRoutingCache()
        assert cache.loaded_at_iso() == "never"

    def test_loaded_at_iso_after_load(self) -> None:
        """After load, loaded_at_iso() returns an ISO timestamp."""
        cache = ProviderRoutingCache()
        settings = _make_settings()
        cache.load_from_config(settings)
        iso = cache.loaded_at_iso()
        assert iso != "never"
        # Should look like an ISO datetime string
        assert "T" in iso

    def test_needs_refresh_always_false(self) -> None:
        """Config-backed cache never needs refresh — always returns False."""
        cache = ProviderRoutingCache()
        assert cache.needs_refresh() is False
        settings = _make_settings()
        cache.load_from_config(settings)
        assert cache.needs_refresh() is False

    def test_load_returns_slot_count(self) -> None:
        """load_from_config() returns the number of distinct (dataset, tf) slots."""
        cache = ProviderRoutingCache()
        settings = _make_settings(
            routing_ohlcv_intraday="alpaca:100",
            routing_ohlcv_eod="eodhd:100",
            routing_quotes="eodhd:100",
            routing_fundamentals="eodhd:100",
        )
        count = cache.load_from_config(settings)
        # 6 intraday TFs + 3 EOD TFs + 1 quotes + 1 fundamentals
        # + 1 news_sentiment + 1 earnings_calendar + 1 insider_transactions = 14
        assert count == 14
