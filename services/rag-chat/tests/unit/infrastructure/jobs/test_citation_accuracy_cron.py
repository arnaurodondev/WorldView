"""Unit tests for citation-accuracy cron job helpers (QA-009, PLAN-0099 W4).

PLAN-0099 W4 migrated the cron from weekly (Sunday 03:00 UTC) to DAILY 03:00 UTC.
The helper renamed from ``_next_sunday_03_utc`` → ``_next_daily_03_utc``. Per R19
we updated (did NOT delete) the boundary cases to cover the new 24h cadence:

- Any weekday before 03:00 UTC: same day at 03:00 (0 days ahead)
- Any weekday at exactly 03:00 UTC: pushed to NEXT day (1 day ahead, not 7)
- Any weekday after 03:00 UTC: next day (1 day ahead)
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

pytestmark = pytest.mark.unit

# _next_daily_03_utc accepts an optional `now` parameter (datetime | None).
# When provided, it calculates relative to that datetime instead of datetime.now().
from rag_chat.infrastructure.jobs.citation_accuracy_cron import _next_daily_03_utc


@pytest.mark.parametrize(
    "now_dt,expected_days_ahead",
    [
        # Monday 10:00 — past 03:00 today → tomorrow (Tuesday) at 03:00 (1 day)
        (datetime(2026, 5, 11, 10, 0, 0, tzinfo=UTC), 1),
        # Saturday 10:00 — past 03:00 → next day (Sunday) (1 day)
        (datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC), 1),
        # Sunday before 03:00 UTC — same day at 03:00 (0 days ahead)
        (datetime(2026, 5, 10, 2, 59, 59, tzinfo=UTC), 0),
        # Sunday at exactly 03:00 UTC — pushed to next day (Monday) (1 day ahead)
        (datetime(2026, 5, 10, 3, 0, 0, tzinfo=UTC), 1),
        # Sunday after 03:00 UTC — next day (Monday) (1 day ahead)
        (datetime(2026, 5, 10, 15, 0, 0, tzinfo=UTC), 1),
        # Wednesday before 03:00 → same day (0 days)
        (datetime(2026, 5, 13, 2, 30, 0, tzinfo=UTC), 0),
        # Wednesday after 03:00 → next day (Thursday) (1 day)
        (datetime(2026, 5, 13, 10, 0, 0, tzinfo=UTC), 1),
    ],
)
def test_next_daily_03_utc_day_offset(now_dt: datetime, expected_days_ahead: int) -> None:
    """_next_daily_03_utc returns the correct next 03:00 UTC for every boundary case."""
    result = _next_daily_03_utc(now_dt)

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


def test_next_daily_03_utc_default_arg() -> None:
    """_next_daily_03_utc() called with no argument returns a future 03:00 UTC within 24h."""
    from datetime import datetime, timedelta

    result = _next_daily_03_utc()
    now = datetime.now(tz=UTC)

    # Must be in the future (or exactly today's 03:00 if we're called pre-03:00)
    assert result > now or result == now.replace(hour=3, minute=0, second=0, microsecond=0)
    # Must be within 24h — daily cadence guarantee
    assert result - now <= timedelta(days=1)
    assert result.hour == 3
    assert result.tzinfo == UTC


# ── MN-1 crashloop guard tests (PLAN-0099 W4) ────────────────────────────────


async def _drain(task: object) -> None:
    """Cancel an asyncio.Task and swallow CancelledError so test teardown is clean."""
    import asyncio as _asyncio

    task.cancel()  # type: ignore[attr-defined]
    try:
        await task  # type: ignore[misc]
    except _asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_first_run_skipped_when_last_run_within_1h() -> None:
    """Last successful run < 1h ago → first execute() is skipped, counter increments."""
    import asyncio as _asyncio
    from datetime import timedelta
    from unittest.mock import AsyncMock, MagicMock

    from rag_chat.infrastructure.jobs.citation_accuracy_cron import (
        _CITATION_CRON_FIRST_RUN_SKIPPED,
        start_citation_accuracy_cron,
    )

    from common.time import utc_now  # type: ignore[import-untyped]

    use_case = MagicMock()
    use_case.execute = AsyncMock(return_value=0.5)

    # Valkey reports the previous run finished 10 minutes ago (within 1h window).
    valkey = MagicMock()
    valkey.get = AsyncMock(return_value=(utc_now() - timedelta(minutes=10)).isoformat())
    valkey.set = AsyncMock()

    before = _CITATION_CRON_FIRST_RUN_SKIPPED._value.get()  # type: ignore[attr-defined]
    task = start_citation_accuracy_cron(use_case, valkey=valkey)
    # Let the task reach the post-guard sleep.
    await _asyncio.sleep(0.05)
    await _drain(task)

    after = _CITATION_CRON_FIRST_RUN_SKIPPED._value.get()  # type: ignore[attr-defined]
    assert after > before, "skipped counter should increment when guard fires"
    use_case.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_first_run_proceeds_when_last_run_old() -> None:
    """Last run > 1h ago → first execute() runs and last_run_at is persisted with TTL=25h."""
    import asyncio as _asyncio
    from datetime import timedelta
    from unittest.mock import AsyncMock, MagicMock

    from rag_chat.infrastructure.jobs.citation_accuracy_cron import (
        _LAST_RUN_KEY,
        start_citation_accuracy_cron,
    )

    from common.time import utc_now  # type: ignore[import-untyped]

    use_case = MagicMock()
    use_case.execute = AsyncMock(return_value=0.5)

    valkey = MagicMock()
    valkey.get = AsyncMock(return_value=(utc_now() - timedelta(hours=2)).isoformat())
    valkey.set = AsyncMock()

    task = start_citation_accuracy_cron(use_case, valkey=valkey)
    await _asyncio.sleep(0.05)
    await _drain(task)

    use_case.execute.assert_awaited()
    assert valkey.set.await_count >= 1
    args = valkey.set.await_args
    assert args.args[0] == _LAST_RUN_KEY
    assert args.kwargs.get("ex") == 25 * 3600


@pytest.mark.asyncio
async def test_first_run_proceeds_when_valkey_unavailable() -> None:
    """valkey=None → guard degrades open and the first execute() proceeds."""
    import asyncio as _asyncio
    from unittest.mock import AsyncMock, MagicMock

    from rag_chat.infrastructure.jobs.citation_accuracy_cron import start_citation_accuracy_cron

    use_case = MagicMock()
    use_case.execute = AsyncMock(return_value=0.5)

    task = start_citation_accuracy_cron(use_case, valkey=None)
    await _asyncio.sleep(0.05)
    await _drain(task)

    use_case.execute.assert_awaited()
