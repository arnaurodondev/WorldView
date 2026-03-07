"""Unit tests for common.time module."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

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
        assert now.tzinfo == timezone.utc


class TestEnsureUtc:
    def test_naive_raises(self) -> None:
        naive = datetime(2025, 1, 1)
        with pytest.raises(ValueError, match="Naive datetime"):
            ensure_utc(naive)

    def test_utc_passthrough(self) -> None:
        dt = datetime(2025, 1, 1, tzinfo=timezone.utc)
        assert ensure_utc(dt) == dt


class TestIso8601Roundtrip:
    def test_roundtrip(self) -> None:
        dt = datetime(2025, 6, 15, 10, 30, 0, 123456, tzinfo=timezone.utc)
        iso = to_iso8601(dt)
        assert from_iso8601(iso) == dt

    def test_parse_z_suffix(self) -> None:
        dt = from_iso8601("2025-06-15T10:30:00.000000Z")
        assert dt.tzinfo is not None


class TestParseBarDate:
    def test_parse(self) -> None:
        dt = parse_bar_date("2025-01-15")
        assert dt.year == 2025
        assert dt.month == 1
        assert dt.day == 15
        assert dt.tzinfo == timezone.utc


class TestParseBarDatetime:
    def test_parse(self) -> None:
        dt = parse_bar_datetime("2025-01-15 14:30:00")
        assert dt.hour == 14
        assert dt.minute == 30
        assert dt.tzinfo == timezone.utc
