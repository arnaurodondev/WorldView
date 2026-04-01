"""Unit tests for BackpressureController (T-C-3-06)."""

from __future__ import annotations

import asyncio

import pytest
from nlp_pipeline.infrastructure.backpressure.controller import BackpressureController


@pytest.mark.unit
class TestBackpressureController:
    def test_initial_state_not_paused(self) -> None:
        controller = BackpressureController(max_depth=20, resume_depth=10)
        assert controller.is_paused is False
        assert controller.current_depth == 0

    def test_invalid_resume_depth_raises(self) -> None:
        with pytest.raises(ValueError, match="resume_depth"):
            BackpressureController(max_depth=10, resume_depth=10)

    @pytest.mark.asyncio
    async def test_acquire_increments_depth(self) -> None:
        controller = BackpressureController(max_depth=20, resume_depth=10)
        await controller.acquire()
        assert controller.current_depth == 1

    @pytest.mark.asyncio
    async def test_release_decrements_depth(self) -> None:
        controller = BackpressureController(max_depth=20, resume_depth=10)
        await controller.acquire()
        controller.release()
        assert controller.current_depth == 0

    @pytest.mark.asyncio
    async def test_depth_cannot_go_below_zero(self) -> None:
        """Release when depth is 0 should clamp to 0, not go negative."""
        controller = BackpressureController(max_depth=20, resume_depth=10)
        controller.release()  # release without acquire
        assert controller.current_depth == 0

    @pytest.mark.asyncio
    async def test_paused_when_max_depth_reached(self) -> None:
        controller = BackpressureController(max_depth=3, resume_depth=1)
        await controller.acquire()
        await controller.acquire()
        await controller.acquire()  # depth == max_depth → paused
        assert controller.is_paused is True

    @pytest.mark.asyncio
    async def test_resumes_when_depth_drops_to_resume_threshold(self) -> None:
        controller = BackpressureController(max_depth=3, resume_depth=1)
        await controller.acquire()
        await controller.acquire()
        await controller.acquire()  # paused
        assert controller.is_paused is True

        controller.release()  # depth=2 — still paused
        assert controller.is_paused is True

        controller.release()  # depth=1 — at resume threshold → resumed
        assert controller.is_paused is False

    @pytest.mark.asyncio
    async def test_context_manager_acquires_and_releases(self) -> None:
        controller = BackpressureController(max_depth=20, resume_depth=10)
        async with controller:
            assert controller.current_depth == 1
        assert controller.current_depth == 0

    @pytest.mark.asyncio
    async def test_context_manager_releases_on_exception(self) -> None:
        controller = BackpressureController(max_depth=20, resume_depth=10)
        try:
            async with controller:
                assert controller.current_depth == 1
                raise ValueError("test error")
        except ValueError:
            pass
        assert controller.current_depth == 0

    @pytest.mark.asyncio
    async def test_gauge_value_matches_current_depth(self) -> None:
        controller = BackpressureController(max_depth=20, resume_depth=10)
        await controller.acquire()
        await controller.acquire()
        assert controller.gauge_value() == 2

    @pytest.mark.asyncio
    async def test_wait_for_resume_returns_immediately_when_not_paused(self) -> None:
        controller = BackpressureController(max_depth=20, resume_depth=10)
        # Should not block at all
        await asyncio.wait_for(controller.wait_for_resume(), timeout=0.5)

    @pytest.mark.asyncio
    async def test_uses_asyncio_not_threading(self) -> None:
        """Verify BackpressureController is asyncio-based (uses asyncio.Semaphore)."""

        controller = BackpressureController(max_depth=20, resume_depth=10)
        # The semaphore must be an asyncio.Semaphore instance
        assert isinstance(controller._semaphore, asyncio.Semaphore)
        # Acquiring must not block the event loop synchronously
        # (i.e., it's a coroutine, not threading.Lock)
        assert asyncio.iscoroutinefunction(controller.acquire)
