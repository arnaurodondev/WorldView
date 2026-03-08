"""Unit tests for contracts.canonical.quotes."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from contracts.canonical.quotes import CanonicalQuote
from contracts.versions import QUOTE_SCHEMA_VERSION


class TestCanonicalQuote:
    def _make_quote(self) -> CanonicalQuote:
        return CanonicalQuote(
            symbol="AAPL",
            exchange="NASDAQ",
            bid=149.90,
            ask=150.10,
            last=150.00,
            volume=5_000_000,
            timestamp=datetime(2025, 1, 15, 15, 30, 0, tzinfo=UTC),
            source="polygon",
        )

    def _make_full_quote(self) -> CanonicalQuote:
        return CanonicalQuote(
            symbol="AAPL",
            exchange="NASDAQ",
            bid=149.90,
            ask=150.10,
            last=150.00,
            volume=5_000_000,
            timestamp=datetime(2025, 1, 15, 15, 30, 0, tzinfo=UTC),
            bid_size=100,
            ask_size=200,
            high=155.0,
            low=148.5,
            open=149.0,
            prev_close=148.0,
            source="polygon",
        )

    def test_schema_version(self) -> None:
        assert self._make_quote().schema_version == QUOTE_SCHEMA_VERSION

    def test_schema_version_is_1(self) -> None:
        assert QUOTE_SCHEMA_VERSION == 1

    def test_roundtrip_minimal(self) -> None:
        quote = self._make_quote()
        restored = CanonicalQuote.from_dict(quote.to_dict())
        assert restored.symbol == quote.symbol
        assert restored.bid == quote.bid
        assert restored.ask == quote.ask
        assert restored.last == quote.last
        assert restored.volume == quote.volume

    def test_roundtrip_full(self) -> None:
        quote = self._make_full_quote()
        restored = CanonicalQuote.from_dict(quote.to_dict())
        assert restored.bid_size == 100
        assert restored.ask_size == 200
        assert restored.high == 155.0
        assert restored.low == 148.5
        assert restored.open == 149.0
        assert restored.prev_close == 148.0

    def test_frozen(self) -> None:
        quote = self._make_quote()
        with pytest.raises(dataclasses.FrozenInstanceError):
            quote.symbol = "MSFT"  # type: ignore[misc]

    def test_optional_fields_default_none(self) -> None:
        quote = self._make_quote()
        assert quote.bid_size is None
        assert quote.ask_size is None
        assert quote.high is None
        assert quote.low is None
        assert quote.open is None
        assert quote.prev_close is None

    def test_to_dict_keys(self) -> None:
        d = self._make_quote().to_dict()
        expected_keys = {
            "symbol",
            "exchange",
            "bid",
            "ask",
            "last",
            "volume",
            "timestamp",
            "bid_size",
            "ask_size",
            "high",
            "low",
            "open",
            "prev_close",
            "source",
            "schema_version",
        }
        assert set(d.keys()) == expected_keys

    def test_timestamp_roundtrip(self) -> None:
        quote = self._make_quote()
        d = quote.to_dict()
        assert isinstance(d["timestamp"], str)
        restored = CanonicalQuote.from_dict(d)
        assert restored.timestamp == quote.timestamp
