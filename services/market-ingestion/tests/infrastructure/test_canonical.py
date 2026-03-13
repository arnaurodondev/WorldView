"""Tests for DefaultCanonicalSerializer (T-MI-20). ≥10 test functions."""

from __future__ import annotations

import json

import pytest
from market_ingestion.infrastructure.adapters.canonical import DefaultCanonicalSerializer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def serializer() -> DefaultCanonicalSerializer:
    return DefaultCanonicalSerializer()


def _ohlcv_row(
    symbol: str = "AAPL",
    exchange: str = "US",
    date: str = "2024-01-02T00:00:00",
    **overrides,
) -> dict:
    row = {
        "symbol": symbol,
        "exchange": exchange,
        "date": date,
        "open": 150.0,
        "high": 155.0,
        "low": 149.0,
        "close": 153.0,
        "volume": 1_000_000,
    }
    row.update(overrides)
    return row


def _quote_row(
    symbol: str = "AAPL",
    exchange: str = "US",
    timestamp: str = "2024-01-02T15:30:00",
    **overrides,
) -> dict:
    row = {
        "symbol": symbol,
        "exchange": exchange,
        "bid": 152.9,
        "ask": 153.1,
        "last": 153.0,
        "volume": 500_000,
        "timestamp": timestamp,
    }
    row.update(overrides)
    return row


def _fundamentals_row(**overrides) -> dict:
    row = {
        "symbol": "AAPL",
        "exchange": "US",
        "period": "annual",
        "report_date": "2023-12-31T00:00:00",
        "revenue": 383_285_000_000.0,
        "net_income": 96_995_000_000.0,
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# serialize_ohlcv
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_serialize_ohlcv_single_bar(serializer):
    result = serializer.serialize_ohlcv([_ohlcv_row()])

    assert isinstance(result, bytes)
    lines = result.decode("utf-8").strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["symbol"] == "AAPL"
    assert parsed["close"] == 153.0


@pytest.mark.unit
def test_serialize_ohlcv_multiple_bars(serializer):
    rows = [_ohlcv_row(date=f"2024-01-0{i}T00:00:00") for i in range(2, 6)]

    result = serializer.serialize_ohlcv(rows)

    lines = result.decode("utf-8").strip().splitlines()
    assert len(lines) == 4


@pytest.mark.unit
def test_serialize_ohlcv_empty_list(serializer):
    result = serializer.serialize_ohlcv([])

    assert result == b""


@pytest.mark.unit
def test_serialize_ohlcv_newline_terminated(serializer):
    result = serializer.serialize_ohlcv([_ohlcv_row()])

    assert result.endswith(b"\n")


@pytest.mark.unit
def test_serialize_ohlcv_invalid_missing_field_raises(serializer):
    bad_row = {"symbol": "AAPL"}  # missing required fields

    with pytest.raises((KeyError, TypeError, ValueError)):
        serializer.serialize_ohlcv([bad_row])


@pytest.mark.unit
def test_serialize_ohlcv_roundtrip_preserves_values(serializer):
    row = _ohlcv_row(open=100.5, high=110.0, low=99.0, close=108.0, volume=42_000)

    result = serializer.serialize_ohlcv([row])
    parsed = json.loads(result.decode("utf-8").strip())

    assert parsed["open"] == 100.5
    assert parsed["high"] == 110.0
    assert parsed["low"] == 99.0
    assert parsed["close"] == 108.0
    assert parsed["volume"] == 42_000


@pytest.mark.unit
def test_serialize_ohlcv_schema_version_present(serializer):
    result = serializer.serialize_ohlcv([_ohlcv_row()])
    parsed = json.loads(result.decode("utf-8").strip())
    assert "schema_version" in parsed


# ---------------------------------------------------------------------------
# serialize_quotes
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_serialize_quotes_single(serializer):
    result = serializer.serialize_quotes([_quote_row()])

    assert isinstance(result, bytes)
    lines = result.decode("utf-8").strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["symbol"] == "AAPL"
    assert parsed["bid"] == 152.9


@pytest.mark.unit
def test_serialize_quotes_empty_list(serializer):
    result = serializer.serialize_quotes([])

    assert result == b""


@pytest.mark.unit
def test_serialize_quotes_multiple(serializer):
    rows = [_quote_row(symbol=f"SYM{i}") for i in range(3)]

    result = serializer.serialize_quotes(rows)

    lines = result.decode("utf-8").strip().splitlines()
    assert len(lines) == 3


@pytest.mark.unit
def test_serialize_quotes_newline_terminated(serializer):
    result = serializer.serialize_quotes([_quote_row()])

    assert result.endswith(b"\n")


@pytest.mark.unit
def test_serialize_quotes_roundtrip(serializer):
    row = _quote_row(bid=200.0, ask=200.1, last=200.05, volume=9_000)

    result = serializer.serialize_quotes([row])
    parsed = json.loads(result.decode("utf-8").strip())

    assert parsed["bid"] == 200.0
    assert parsed["ask"] == 200.1
    assert parsed["last"] == 200.05
    assert parsed["volume"] == 9_000


# ---------------------------------------------------------------------------
# serialize_fundamentals
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_serialize_fundamentals_single_line(serializer):
    result = serializer.serialize_fundamentals(_fundamentals_row())

    assert isinstance(result, bytes)
    lines = result.decode("utf-8").strip().splitlines()
    assert len(lines) == 1


@pytest.mark.unit
def test_serialize_fundamentals_newline_terminated(serializer):
    result = serializer.serialize_fundamentals(_fundamentals_row())

    assert result.endswith(b"\n")


@pytest.mark.unit
def test_serialize_fundamentals_preserves_values(serializer):
    row = _fundamentals_row(revenue=999.0, net_income=111.0, eps=3.14)

    result = serializer.serialize_fundamentals(row)
    parsed = json.loads(result.decode("utf-8").strip())

    assert parsed["symbol"] == "AAPL"
    assert parsed["revenue"] == 999.0
    assert parsed["eps"] == pytest.approx(3.14)


@pytest.mark.unit
def test_serialize_fundamentals_variant_param_ignored(serializer):
    """variant is informational only — output should be the same dict."""
    row = _fundamentals_row()

    result_annual = serializer.serialize_fundamentals(row, variant="annual")
    result_quarterly = serializer.serialize_fundamentals(row, variant="quarterly")

    assert json.loads(result_annual) == json.loads(result_quarterly)


@pytest.mark.unit
def test_serialize_fundamentals_schema_version_present(serializer):
    result = serializer.serialize_fundamentals(_fundamentals_row())
    parsed = json.loads(result.decode("utf-8").strip())
    assert "schema_version" in parsed
