"""Unit tests for scheduler exponential backoff + hot-add/remove (Wave 3)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from content_ingestion.domain.entities import Source, SourceType
from content_ingestion.infrastructure.scheduler.scheduler import IngestionScheduler

pytestmark = pytest.mark.unit


def _make_source(
    name: str = "test",
    source_type: SourceType = SourceType.EODHD,
    enabled: bool = True,
) -> Source:
    return Source(name=name, source_type=source_type, enabled=enabled, config={})


class TestExponentialBackoff:
    async def test_first_failure_doubles_delay(self) -> None:
        """After 1 failure, delay = interval * 2^1."""
        calls: list[float] = []
        call_count = 0

        async def fail_once(source: Source) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient")

        original_sleep = asyncio.sleep

        async def tracking_sleep(delay: float) -> None:
            calls.append(delay)
            # Stop after second sleep to prevent infinite loop
            if len(calls) >= 2:
                raise asyncio.CancelledError
            await original_sleep(0)  # yield control

        scheduler = IngestionScheduler(interval_seconds=10, run_fn=fail_once, max_backoff_seconds=3600)
        scheduler._running = True

        source = _make_source()
        import unittest.mock

        with unittest.mock.patch("asyncio.sleep", side_effect=tracking_sleep):
            with pytest.raises(asyncio.CancelledError):
                await scheduler._poll_loop(source)

        # First sleep: 10 * 2^1 = 20 (after failure)
        assert calls[0] == 20.0
        # Second sleep: 10 (after success, reset)
        assert calls[1] == 10.0

    async def test_third_failure_delay_grows(self) -> None:
        """After 3 consecutive failures, delay = interval * 2^3."""
        calls: list[float] = []
        fail_count = 0

        async def always_fail(source: Source) -> None:
            nonlocal fail_count
            fail_count += 1
            raise RuntimeError("persistent")

        async def tracking_sleep(delay: float) -> None:
            calls.append(delay)
            if len(calls) >= 3:
                raise asyncio.CancelledError

        scheduler = IngestionScheduler(interval_seconds=10, run_fn=always_fail, max_backoff_seconds=3600)
        scheduler._running = True

        import unittest.mock

        with unittest.mock.patch("asyncio.sleep", side_effect=tracking_sleep):
            with pytest.raises(asyncio.CancelledError):
                await scheduler._poll_loop(_make_source())

        assert calls[0] == 20.0  # 10 * 2^1
        assert calls[1] == 40.0  # 10 * 2^2
        assert calls[2] == 80.0  # 10 * 2^3

    async def test_backoff_capped_at_max(self) -> None:
        """Delay never exceeds max_backoff_seconds."""
        calls: list[float] = []

        async def always_fail(source: Source) -> None:
            raise RuntimeError("fail")

        async def tracking_sleep(delay: float) -> None:
            calls.append(delay)
            if len(calls) >= 15:
                raise asyncio.CancelledError

        scheduler = IngestionScheduler(interval_seconds=10, run_fn=always_fail, max_backoff_seconds=100)
        scheduler._running = True

        import unittest.mock

        with unittest.mock.patch("asyncio.sleep", side_effect=tracking_sleep):
            with pytest.raises(asyncio.CancelledError):
                await scheduler._poll_loop(_make_source())

        # All delays should be capped at 100
        for delay in calls:
            assert delay <= 100.0

    async def test_backoff_resets_on_success(self) -> None:
        """After a failure then success, delay resets to base interval."""
        calls: list[float] = []
        call_count = 0

        async def fail_then_succeed(source: Source) -> None:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RuntimeError("fail")

        async def tracking_sleep(delay: float) -> None:
            calls.append(delay)
            if len(calls) >= 3:
                raise asyncio.CancelledError

        scheduler = IngestionScheduler(interval_seconds=10, run_fn=fail_then_succeed, max_backoff_seconds=3600)
        scheduler._running = True

        import unittest.mock

        with unittest.mock.patch("asyncio.sleep", side_effect=tracking_sleep):
            with pytest.raises(asyncio.CancelledError):
                await scheduler._poll_loop(_make_source())

        # calls[0] = 20 (fail 1), calls[1] = 40 (fail 2), calls[2] = 10 (success reset)
        assert calls[0] == 20.0
        assert calls[1] == 40.0
        assert calls[2] == 10.0


class TestAddRemoveSource:
    async def test_add_source_starts_polling(self) -> None:
        run_fn = AsyncMock()
        scheduler = IngestionScheduler(interval_seconds=60, run_fn=run_fn)
        scheduler._running = True

        source = _make_source(name="new-source")
        result = scheduler.add_source(source)

        assert result is True
        assert "new-source" in scheduler._tasks
        await scheduler.stop()

    async def test_add_source_rejects_duplicate(self) -> None:
        run_fn = AsyncMock()
        scheduler = IngestionScheduler(interval_seconds=60, run_fn=run_fn)
        scheduler._running = True

        source = _make_source(name="dup")
        scheduler.add_source(source)
        result = scheduler.add_source(source)

        assert result is False
        await scheduler.stop()

    async def test_add_source_rejects_disabled(self) -> None:
        run_fn = AsyncMock()
        scheduler = IngestionScheduler(interval_seconds=60, run_fn=run_fn)
        scheduler._running = True

        source = _make_source(name="disabled", enabled=False)
        result = scheduler.add_source(source)

        assert result is False
        await scheduler.stop()

    async def test_add_source_rejects_when_not_running(self) -> None:
        run_fn = AsyncMock()
        scheduler = IngestionScheduler(interval_seconds=60, run_fn=run_fn)
        # Not started — _running is False

        source = _make_source()
        result = scheduler.add_source(source)

        assert result is False

    async def test_remove_source_cancels_task(self) -> None:
        run_fn = AsyncMock()
        scheduler = IngestionScheduler(interval_seconds=3600, run_fn=run_fn)
        scheduler._running = True

        source = _make_source(name="removable")
        scheduler.add_source(source)
        assert "removable" in scheduler._tasks

        result = scheduler.remove_source("removable")
        assert result is True
        assert "removable" not in scheduler._tasks
        await scheduler.stop()

    async def test_remove_source_not_found_returns_false(self) -> None:
        run_fn = AsyncMock()
        scheduler = IngestionScheduler(interval_seconds=60, run_fn=run_fn)
        scheduler._running = True

        result = scheduler.remove_source("nonexistent")
        assert result is False
        await scheduler.stop()
