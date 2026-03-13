"""Tests for market_ingestion domain value objects."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from market_ingestion.domain.value_objects import DateRange, InstrumentKey, ObjectRef, Timeframe

UTC = UTC


# ── Timeframe ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_timeframe_valid_values() -> None:
    valid = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1mo", "1y"]
    for v in valid:
        tf = Timeframe(v)
        assert str(tf) == v
        assert tf.value == v


@pytest.mark.unit
def test_timeframe_invalid_raises() -> None:
    with pytest.raises(ValueError, match="Invalid timeframe"):
        Timeframe("2d")


@pytest.mark.unit
def test_timeframe_empty_string_raises() -> None:
    with pytest.raises(ValueError):
        Timeframe("")


@pytest.mark.unit
def test_timeframe_case_sensitive() -> None:
    with pytest.raises(ValueError):
        Timeframe("1D")  # must be lowercase


@pytest.mark.unit
def test_timeframe_equality_with_string() -> None:
    tf = Timeframe("1d")
    assert tf == "1d"
    assert tf != "1h"


@pytest.mark.unit
def test_timeframe_equality_with_timeframe() -> None:
    assert Timeframe("1h") == Timeframe("1h")
    assert Timeframe("1h") != Timeframe("4h")


@pytest.mark.unit
def test_timeframe_hashable() -> None:
    s: set[Timeframe] = {Timeframe("1d"), Timeframe("1h"), Timeframe("1d")}
    assert len(s) == 2


@pytest.mark.unit
def test_timeframe_repr() -> None:
    assert repr(Timeframe("1w")) == "Timeframe('1w')"


# ── ObjectRef ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_object_ref_field_access() -> None:
    ref = ObjectRef(
        bucket="bronze",
        key="market-ingestion/ohlcv/AAPL.US/raw.json",
        sha256="abc123",
        byte_length=1024,
        mime_type="application/json",
    )
    assert ref.bucket == "bronze"
    assert ref.key == "market-ingestion/ohlcv/AAPL.US/raw.json"
    assert ref.sha256 == "abc123"
    assert ref.byte_length == 1024
    assert ref.mime_type == "application/json"


@pytest.mark.unit
def test_object_ref_immutable() -> None:
    ref = ObjectRef(bucket="b", key="k", sha256="s", byte_length=0, mime_type="m")
    with pytest.raises(AttributeError):
        ref.bucket = "other"  # type: ignore[misc]


@pytest.mark.unit
def test_object_ref_equality() -> None:
    r1 = ObjectRef(bucket="b", key="k", sha256="s", byte_length=0, mime_type="m")
    r2 = ObjectRef(bucket="b", key="k", sha256="s", byte_length=0, mime_type="m")
    assert r1 == r2


@pytest.mark.unit
def test_object_ref_hashable() -> None:
    ref = ObjectRef(bucket="b", key="k", sha256="s", byte_length=0, mime_type="m")
    assert hash(ref) == hash(ref)
    s = {ref}
    assert ref in s


# ── InstrumentKey ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_instrument_key_with_exchange() -> None:
    ik = InstrumentKey(symbol="AAPL", exchange="NASDAQ")
    assert ik.symbol == "AAPL"
    assert ik.exchange == "NASDAQ"


@pytest.mark.unit
def test_instrument_key_optional_exchange() -> None:
    ik = InstrumentKey(symbol="BTC-USD")
    assert ik.symbol == "BTC-USD"
    assert ik.exchange is None


@pytest.mark.unit
def test_instrument_key_immutable() -> None:
    ik = InstrumentKey(symbol="TSLA", exchange="NASDAQ")
    with pytest.raises(AttributeError):
        ik.symbol = "AAPL"  # type: ignore[misc]


# ── DateRange ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_date_range_valid() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 12, 31, tzinfo=UTC)
    dr = DateRange(start=start, end=end)
    assert dr.start == start
    assert dr.end == end


@pytest.mark.unit
def test_date_range_rejects_equal_start_end() -> None:
    ts = datetime(2024, 6, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="strictly before end"):
        DateRange(start=ts, end=ts)


@pytest.mark.unit
def test_date_range_rejects_start_after_end() -> None:
    with pytest.raises(ValueError, match="strictly before end"):
        DateRange(start=datetime(2024, 12, 1, tzinfo=UTC), end=datetime(2024, 1, 1, tzinfo=UTC))


@pytest.mark.unit
def test_date_range_rejects_naive_start() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        DateRange(start=datetime(2024, 1, 1), end=datetime(2024, 12, 31, tzinfo=UTC))  # noqa: DTZ001


@pytest.mark.unit
def test_date_range_rejects_naive_end() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        DateRange(start=datetime(2024, 1, 1, tzinfo=UTC), end=datetime(2024, 12, 31))  # noqa: DTZ001


@pytest.mark.unit
def test_date_range_immutable() -> None:
    dr = DateRange(start=datetime(2024, 1, 1, tzinfo=UTC), end=datetime(2024, 12, 31, tzinfo=UTC))
    with pytest.raises(AttributeError):
        dr.start = datetime(2025, 1, 1, tzinfo=UTC)  # type: ignore[misc]
