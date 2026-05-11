"""Unit tests for _parse_event_date helper (EconomicEventsDatasetConsumer, PRD-0018 §6 Worker 13D-6)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

pytestmark = pytest.mark.unit


def _parse(date_str: str):  # type: ignore[no-untyped-def]
    # D-W5: _parse_event_date was moved from the retired economic_events_worker
    # to the new Kafka-driven consumer.
    from knowledge_graph.infrastructure.messaging.consumers.economic_events_dataset_consumer import _parse_event_date

    return _parse_event_date(date_str)


class TestParseEventDate:
    def test_date_only_format(self) -> None:
        """ISO-8601 date-only string returns midnight UTC datetime."""
        result = _parse("2026-04-01")
        assert result == datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)

    def test_full_iso8601_with_time(self) -> None:
        """ISO-8601 with time component returns aware datetime at that time."""
        result = _parse("2026-04-01T14:30:00")
        assert result == datetime(2026, 4, 1, 14, 30, 0, tzinfo=UTC)

    def test_result_is_always_utc(self) -> None:
        """Returned datetime is always UTC-aware."""
        result = _parse("2026-01-15")
        assert result is not None
        assert result.tzinfo is UTC

    def test_empty_string_returns_none(self) -> None:
        """Empty string returns None (unreleased event guard)."""
        assert _parse("") is None

    def test_invalid_string_returns_none(self) -> None:
        """Unparseable string returns None without raising."""
        assert _parse("not-a-date") is None

    def test_partial_date_missing_day_returns_none(self) -> None:
        """Partial date missing day component returns None."""
        assert _parse("2026-04") is None

    def test_leading_trailing_spaces_returns_none(self) -> None:
        """String with only spaces is treated as unparseable (returns None)."""
        assert _parse("   ") is None

    def test_iso8601_with_milliseconds_truncated(self) -> None:
        """String with sub-second precision is handled (first 19 chars parsed)."""
        # "2026-04-01T14:30:00" is the first 19 chars — time part parsed correctly
        result = _parse("2026-04-01T14:30:00.123456")
        assert result == datetime(2026, 4, 1, 14, 30, 0, tzinfo=UTC)

    def test_midnight_date(self) -> None:
        """Date at year boundary is parsed correctly."""
        result = _parse("2026-01-01")
        assert result == datetime(2026, 1, 1, tzinfo=UTC)
