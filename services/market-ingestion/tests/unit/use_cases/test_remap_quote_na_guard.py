"""Unit tests for the EODHD "NA" parse guard in _remap_quote.

EODHD real-time responses report missing data as the literal string "NA".
"NA" is truthy, so a bare ``raw.get("last") or raw.get("close")`` would pass
it downstream and crash CanonicalQuote/Decimal parsing.  ``_num`` /
``_int_or_none`` coerce "NA"/""/None/garbage to None before any fallback.
"""

from __future__ import annotations

import pytest
from market_ingestion.application.use_cases.strategies.canonicalize import (
    _int_or_none,
    _num,
    _remap_quote,
)

pytestmark = pytest.mark.unit


# ── _num / _int_or_none coercion ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("NA", None),
        ("", None),
        (None, None),
        ("garbage", None),
        ("123.45", 123.45),
        (123.45, 123.45),
        (0, 0.0),
        (0.0, 0.0),
    ],
)
def test_num_coercion(value: object, expected: float | None) -> None:
    assert _num(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("NA", None),
        ("", None),
        (None, None),
        ("1234", 1234),
        ("1234.0", 1234),  # EODHD sometimes sends float-strings for volume
        (1234, 1234),
    ],
)
def test_int_or_none_coercion(value: object, expected: int | None) -> None:
    assert _int_or_none(value) == expected


# ── _remap_quote with NA fields ──────────────────────────────────────────────


def test_remap_quote_all_na_fields_do_not_raise() -> None:
    """A fully-NA EODHD response (delisted/unsupported ticker) must not raise."""
    raw = {
        "code": "DEAD.US",
        "timestamp": "NA",
        "open": "NA",
        "high": "NA",
        "low": "NA",
        "close": "NA",
        "volume": "NA",
        "previousClose": "NA",
        "change": "NA",
        "change_p": "NA",
    }
    result = _remap_quote(raw, symbol="DEAD", exchange="US", source="eodhd")

    # "NA" close must not leak through as last/bid/ask
    assert result["last"] == 0.0  # FIX-Q1 fallback, logged not raised
    assert result["bid"] == 0.0
    assert result["ask"] == 0.0
    assert result["volume"] is None
    assert result["high"] is None
    assert result["low"] is None
    assert result["open"] is None
    assert result["prev_close"] is None
    # "NA" timestamp falls back to now() — never the literal string "NA"
    assert result["timestamp"] != "NA"


def test_remap_quote_na_last_falls_back_to_valid_close() -> None:
    """'NA' is truthy — _num must run BEFORE the `or` fallback so a valid
    close is still picked up when last is 'NA'."""
    raw = {"last": "NA", "close": 101.5, "timestamp": 1_770_000_000, "volume": 500}
    result = _remap_quote(raw, symbol="AAPL", exchange="US", source="eodhd")

    assert result["last"] == 101.5
    assert result["bid"] == 101.5  # bid/ask fall back to last
    assert result["ask"] == 101.5
    assert result["volume"] == 500


def test_remap_quote_valid_floats_unchanged() -> None:
    """Well-formed numeric payloads pass through untouched."""
    raw = {
        "close": 250.25,
        "bid": 250.20,
        "ask": 250.30,
        "volume": 1_000_000,
        "high": 252.0,
        "low": 248.0,
        "open": 249.0,
        "previousClose": 247.5,
        "timestamp": 1_770_000_000,
    }
    result = _remap_quote(raw, symbol="MSFT", exchange="US", source="eodhd")

    assert result["last"] == 250.25
    assert result["bid"] == 250.20
    assert result["ask"] == 250.30
    assert result["volume"] == 1_000_000
    assert result["high"] == 252.0
    assert result["low"] == 248.0
    assert result["open"] == 249.0
    assert result["prev_close"] == 247.5


def test_remap_quote_volume_na_is_none() -> None:
    raw = {"close": 10.0, "volume": "NA", "timestamp": 1_770_000_000}
    result = _remap_quote(raw, symbol="X", exchange="US", source="eodhd")
    assert result["volume"] is None
    assert result["last"] == 10.0
