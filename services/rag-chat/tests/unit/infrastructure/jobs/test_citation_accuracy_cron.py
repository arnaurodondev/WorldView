"""Unit tests for citation-accuracy cron job helpers (QA-009).

Tests for _next_sunday_03_utc() with 6 boundary cases:
- Monday through Saturday: verify correct days-ahead calculation
- Sunday before 03:00 UTC: same day at 03:00
- Sunday at exactly 03:00 UTC: pushes to next week (7 days)
- Sunday after 03:00 UTC: next week (7 days)
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

pytestmark = pytest.mark.unit

# _next_sunday_03_utc accepts an optional `now` parameter (datetime | None).
# When provided, it calculates relative to that datetime instead of datetime.now().
from rag_chat.infrastructure.jobs.citation_accuracy_cron import _next_sunday_03_utc


@pytest.mark.parametrize(
    "now_dt,expected_days_ahead",
    [
        # Monday (weekday=0) — next Sunday is 6 days away
        (datetime(2026, 5, 11, 10, 0, 0, tzinfo=UTC), 6),
        # Saturday (weekday=5) — next Sunday is 1 day away
        (datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC), 1),
        # Sunday (weekday=6) before 03:00 UTC — same day at 03:00 (0 days ahead)
        (datetime(2026, 5, 10, 2, 59, 59, tzinfo=UTC), 0),
        # Sunday at exactly 03:00 UTC — pushed to next Sunday (7 days ahead)
        (datetime(2026, 5, 10, 3, 0, 0, tzinfo=UTC), 7),
        # Sunday after 03:00 UTC — next Sunday (7 days ahead)
        (datetime(2026, 5, 10, 15, 0, 0, tzinfo=UTC), 7),
        # Wednesday (weekday=2) — next Sunday is 4 days away
        (datetime(2026, 5, 13, 10, 0, 0, tzinfo=UTC), 4),
    ],
)
def test_next_sunday_03_utc_day_offset(now_dt: datetime, expected_days_ahead: int) -> None:
    """_next_sunday_03_utc returns the correct Sunday 03:00 UTC for every boundary case."""
    result = _next_sunday_03_utc(now_dt)

    # Result must always be a Sunday
    assert result.weekday() == 6, f"Expected Sunday (weekday=6), got weekday={result.weekday()}"

    # Result must always be at 03:00:00 UTC
    assert result.hour == 3, f"Expected hour=3, got hour={result.hour}"
    assert result.minute == 0
    assert result.second == 0
    assert result.microsecond == 0

    # Result must be timezone-aware UTC
    assert result.tzinfo == UTC, f"Expected UTC tzinfo, got {result.tzinfo}"

    # Verify the number of calendar days ahead
    delta = result.date() - now_dt.date()
    assert delta.days == expected_days_ahead, (
        f"For now_dt={now_dt.isoformat()}: expected {expected_days_ahead} days ahead, "
        f"got {delta.days} (result={result.isoformat()})"
    )


def test_next_sunday_03_utc_default_arg() -> None:
    """_next_sunday_03_utc() called with no argument returns a future Sunday 03:00 UTC."""
    from datetime import datetime

    result = _next_sunday_03_utc()
    now = datetime.now(tz=UTC)

    # Must be in the future (or, at minimum, same second on the exact boundary)
    assert result > now or result == now.replace(hour=3, minute=0, second=0, microsecond=0)
    assert result.weekday() == 6
    assert result.hour == 3
    assert result.tzinfo == UTC
