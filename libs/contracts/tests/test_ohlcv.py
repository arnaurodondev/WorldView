"""Unit tests for contracts.canonical.ohlcv."""

from __future__ import annotations

from datetime import datetime, timezone

from contracts.canonical.ohlcv import CanonicalOHLCVBar
from contracts.versions import OHLCV_SCHEMA_VERSION


class TestCanonicalOHLCVBar:
    def _make_bar(self) -> CanonicalOHLCVBar:
        return CanonicalOHLCVBar(
            symbol="AAPL",
            exchange="US",
            date=datetime(2025, 1, 15, tzinfo=timezone.utc),
            open=150.0,
            high=155.0,
            low=149.0,
            close=154.0,
            volume=1_000_000,
            adjusted_close=154.0,
            source="eod",
        )

    def test_schema_version(self) -> None:
        bar = self._make_bar()
        assert bar.schema_version == OHLCV_SCHEMA_VERSION

    def test_roundtrip(self) -> None:
        bar = self._make_bar()
        d = bar.to_dict()
        restored = CanonicalOHLCVBar.from_dict(d)
        assert restored.symbol == bar.symbol
        assert restored.close == bar.close
        assert restored.volume == bar.volume

    def test_frozen(self) -> None:
        bar = self._make_bar()
        import dataclasses
        with __import__("pytest").raises(dataclasses.FrozenInstanceError):
            bar.symbol = "MSFT"  # type: ignore[misc]
