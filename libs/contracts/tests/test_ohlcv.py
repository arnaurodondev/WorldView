"""Unit tests for contracts.canonical.ohlcv."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from contracts.canonical.ohlcv import CanonicalOHLCVBar
from contracts.versions import OHLCV_SCHEMA_VERSION


class TestCanonicalOHLCVBar:
    def _make_bar(self) -> CanonicalOHLCVBar:
        return CanonicalOHLCVBar(
            symbol="AAPL",
            exchange="US",
            date=datetime(2025, 1, 15, tzinfo=UTC),
            open=150.0,
            high=155.0,
            low=149.0,
            close=154.0,
            volume=1_000_000,
            adjusted_close=154.0,
            source="eod",
        )

    def _make_full_bar(self) -> CanonicalOHLCVBar:
        return CanonicalOHLCVBar(
            symbol="AAPL",
            exchange="US",
            date=datetime(2025, 1, 15, tzinfo=UTC),
            open=150.0,
            high=155.0,
            low=149.0,
            close=154.0,
            volume=1_000_000,
            adjusted_close=154.0,
            source="eod",
            provider="alpha_vantage",
            timeframe="1d",
            fetched_at=datetime(2025, 1, 15, 18, 0, 0, tzinfo=UTC),
        )

    def test_schema_version(self) -> None:
        bar = self._make_bar()
        assert bar.schema_version == OHLCV_SCHEMA_VERSION

    def test_schema_version_is_1(self) -> None:
        assert OHLCV_SCHEMA_VERSION == 1

    def test_roundtrip(self) -> None:
        bar = self._make_bar()
        d = bar.to_dict()
        restored = CanonicalOHLCVBar.from_dict(d)
        assert restored.symbol == bar.symbol
        assert restored.close == bar.close
        assert restored.volume == bar.volume

    def test_roundtrip_with_new_fields(self) -> None:
        bar = self._make_full_bar()
        d = bar.to_dict()
        restored = CanonicalOHLCVBar.from_dict(d)
        assert restored.provider == "alpha_vantage"
        assert restored.timeframe == "1d"
        assert restored.fetched_at is not None
        assert restored.fetched_at == bar.fetched_at

    def test_frozen(self) -> None:
        bar = self._make_bar()
        with pytest.raises(dataclasses.FrozenInstanceError):
            bar.symbol = "MSFT"  # type: ignore[misc]

    def test_optional_fields_defaults(self) -> None:
        bar = self._make_bar()
        assert bar.provider == ""
        assert bar.timeframe == "1d"
        assert bar.fetched_at is None

    def test_to_dict_includes_new_fields(self) -> None:
        bar = self._make_full_bar()
        d = bar.to_dict()
        assert "provider" in d
        assert "timeframe" in d
        assert "fetched_at" in d
        assert d["provider"] == "alpha_vantage"
        assert d["timeframe"] == "1d"
        assert d["fetched_at"] is not None

    def test_to_dict_fetched_at_none(self) -> None:
        bar = self._make_bar()
        d = bar.to_dict()
        assert d["fetched_at"] is None

    def test_from_dict_backward_compat_no_new_fields(self) -> None:
        d = {
            "symbol": "MSFT",
            "exchange": "US",
            "date": "2025-01-15T00:00:00+00:00",
            "open": 300.0,
            "high": 305.0,
            "low": 299.0,
            "close": 302.0,
            "volume": 500_000,
        }
        bar = CanonicalOHLCVBar.from_dict(d)
        assert bar.symbol == "MSFT"
        assert bar.provider == ""
        assert bar.timeframe == "1d"
        assert bar.fetched_at is None
