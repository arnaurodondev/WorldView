"""Unit tests for common.time module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from common.time import (
    ensure_utc,
    from_iso8601,
    parse_bar_date,
    parse_bar_datetime,
    to_iso8601,
    utc_now,
)


class TestUtcNow:
    def test_returns_utc_aware(self) -> None:
        now = utc_now()
        assert now.tzinfo is not None
        assert now.tzinfo == UTC

    def test_returns_datetime(self) -> None:
        assert isinstance(utc_now(), datetime)

    def test_monotonically_non_decreasing(self) -> None:
        t1 = utc_now()
        t2 = utc_now()
        assert t2 >= t1


class TestEnsureUtc:
    def test_naive_raises(self) -> None:
        naive = datetime(2025, 1, 1)  # noqa: DTZ001
        with pytest.raises(ValueError, match="Naive datetime"):
            ensure_utc(naive)

    def test_utc_passthrough(self) -> None:
        dt = datetime(2025, 1, 1, tzinfo=UTC)
        result = ensure_utc(dt)
        assert result == dt
        assert result.tzinfo == UTC

    def test_non_utc_aware_converted(self) -> None:
        eastern = ZoneInfo("America/New_York")
        dt_eastern = datetime(2025, 6, 15, 12, 0, 0, tzinfo=eastern)
        result = ensure_utc(dt_eastern)
        assert result.tzinfo == UTC
        # 12:00 Eastern (UTC-4 in summer) == 16:00 UTC
        assert result.hour == 16

    def test_utc_plus_zero_offset_passthrough(self) -> None:
        utc_plus_zero = timezone(timedelta(0))
        dt = datetime(2025, 1, 1, tzinfo=utc_plus_zero)
        result = ensure_utc(dt)
        assert result.tzinfo == UTC


class TestToIso8601:
    def test_basic_format(self) -> None:
        dt = datetime(2025, 6, 15, 10, 30, 0, 0, tzinfo=UTC)
        iso = to_iso8601(dt)
        assert iso == "2025-06-15T10:30:00.000000Z"

    def test_with_microseconds(self) -> None:
        dt = datetime(2025, 6, 15, 10, 30, 0, 123456, tzinfo=UTC)
        iso = to_iso8601(dt)
        assert iso == "2025-06-15T10:30:00.123456Z"

    def test_midnight(self) -> None:
        dt = datetime(2025, 1, 1, 0, 0, 0, 0, tzinfo=UTC)
        iso = to_iso8601(dt)
        assert iso == "2025-01-01T00:00:00.000000Z"

    def test_end_of_day(self) -> None:
        dt = datetime(2025, 12, 31, 23, 59, 59, 999999, tzinfo=UTC)
        iso = to_iso8601(dt)
        assert iso == "2025-12-31T23:59:59.999999Z"

    def test_raises_on_naive(self) -> None:
        naive = datetime(2025, 1, 1)  # noqa: DTZ001
        with pytest.raises(ValueError, match="Naive datetime"):
            to_iso8601(naive)

    def test_ends_with_z(self) -> None:
        iso = to_iso8601(utc_now())
        assert iso.endswith("Z")


class TestFromIso8601:
    def test_parse_z_suffix(self) -> None:
        dt = from_iso8601("2025-06-15T10:30:00.000000Z")
        assert dt.tzinfo is not None
        assert dt.tzinfo == UTC

    def test_parse_plus_zero_offset(self) -> None:
        dt = from_iso8601("2025-06-15T10:30:00+00:00")
        assert dt.tzinfo == UTC

    def test_parse_microseconds(self) -> None:
        dt = from_iso8601("2025-06-15T10:30:00.123456Z")
        assert dt.microsecond == 123456

    def test_parse_no_microseconds(self) -> None:
        dt = from_iso8601("2025-06-15T10:30:00Z")
        assert dt.second == 0
        assert dt.tzinfo == UTC

    def test_roundtrip(self) -> None:
        original = "2025-06-15T10:30:00.123456Z"
        dt = from_iso8601(original)
        result = to_iso8601(dt)
        assert result == original


class TestIso8601Roundtrip:
    def test_roundtrip_with_microseconds(self) -> None:
        dt = datetime(2025, 6, 15, 10, 30, 0, 123456, tzinfo=UTC)
        iso = to_iso8601(dt)
        assert from_iso8601(iso) == dt

    def test_roundtrip_midnight(self) -> None:
        dt = datetime(2025, 1, 1, 0, 0, 0, 0, tzinfo=UTC)
        assert from_iso8601(to_iso8601(dt)) == dt

    def test_multiple_roundtrips_stable(self) -> None:
        dt = datetime(2025, 3, 15, 8, 45, 12, 500000, tzinfo=UTC)
        s1 = to_iso8601(dt)
        s2 = to_iso8601(from_iso8601(s1))
        assert s1 == s2


class TestParseBarDate:
    def test_parse(self) -> None:
        dt = parse_bar_date("2025-01-15")
        assert dt.year == 2025
        assert dt.month == 1
        assert dt.day == 15
        assert dt.tzinfo == UTC

    def test_midnight(self) -> None:
        dt = parse_bar_date("2025-01-15")
        assert dt.hour == 0
        assert dt.minute == 0
        assert dt.second == 0

    def test_first_of_year(self) -> None:
        dt = parse_bar_date("2025-01-01")
        assert dt.year == 2025
        assert dt.month == 1
        assert dt.day == 1

    def test_last_of_year(self) -> None:
        dt = parse_bar_date("2025-12-31")
        assert dt.month == 12
        assert dt.day == 31

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_bar_date("15-01-2025")

    def test_returns_utc(self) -> None:
        dt = parse_bar_date("2025-06-01")
        assert dt.tzinfo == UTC


class TestParseBarDatetime:
    def test_parse(self) -> None:
        dt = parse_bar_datetime("2025-01-15 14:30:00")
        assert dt.hour == 14
        assert dt.minute == 30
        assert dt.tzinfo == UTC

    def test_midnight(self) -> None:
        dt = parse_bar_datetime("2025-01-15 00:00:00")
        assert dt.hour == 0
        assert dt.second == 0

    def test_end_of_day(self) -> None:
        dt = parse_bar_datetime("2025-01-15 23:59:59")
        assert dt.hour == 23
        assert dt.minute == 59
        assert dt.second == 59

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_bar_datetime("2025-01-15T14:30:00")

    def test_returns_utc(self) -> None:
        dt = parse_bar_datetime("2025-06-01 10:00:00")
        assert dt.tzinfo == UTC
