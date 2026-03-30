"""Unit tests for SchedulerProcess."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from content_ingestion.application.use_cases.schedule_sources import SchedulerTickResult

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings() -> MagicMock:
    settings = MagicMock()
    settings.db_url = "postgresql+asyncpg://u:p@localhost:5432/test"
    settings.db_url_read = ""
    settings.scheduler_tick_interval_seconds = 0.05  # fast for tests
    settings.scheduler_max_tasks_per_tick = 100
    settings.scheduler_interval_seconds = 300
    return settings


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSchedulerProcessTick:
    @patch("content_ingestion.infrastructure.scheduler.scheduler_process._build_factories")
    @patch("content_ingestion.infrastructure.scheduler.scheduler_process.ScheduleDueSourcesUseCase")
    async def test_tick_calls_use_case_and_logs(self, mock_uc_cls: MagicMock, mock_build: MagicMock) -> None:
        from content_ingestion.infrastructure.scheduler.scheduler_process import SchedulerProcess

        mock_engine = MagicMock()
        mock_factory = MagicMock()
        mock_build.return_value = (mock_engine, mock_factory, mock_factory)

        mock_uc_instance = AsyncMock()
        mock_uc_instance.execute.return_value = SchedulerTickResult(tasks_enqueued=2, sources_evaluated=5)
        mock_uc_cls.return_value = mock_uc_instance

        settings = _make_settings()
        process = SchedulerProcess(settings=settings)

        await process._tick()

        mock_uc_instance.execute.assert_awaited_once()


class TestSchedulerProcessStop:
    @patch("content_ingestion.infrastructure.scheduler.scheduler_process._build_factories")
    async def test_stop_causes_run_to_exit(self, mock_build: MagicMock) -> None:
        from content_ingestion.infrastructure.scheduler.scheduler_process import SchedulerProcess

        mock_engine = MagicMock()
        mock_factory = MagicMock()
        mock_build.return_value = (mock_engine, mock_factory, mock_factory)

        settings = _make_settings()
        process = SchedulerProcess(settings=settings)

        # Patch _tick to just stop the process
        call_count = 0

        async def _tick_then_stop() -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                process.stop()

        process._tick = _tick_then_stop  # type: ignore[assignment]

        await process.run()

        assert call_count >= 2
        assert process._stop_event.is_set()


class TestSchedulerProcessTickError:
    @patch("content_ingestion.infrastructure.scheduler.scheduler_process._build_factories")
    @patch("content_ingestion.infrastructure.scheduler.scheduler_process.ScheduleDueSourcesUseCase")
    async def test_tick_error_does_not_crash_process(self, mock_uc_cls: MagicMock, mock_build: MagicMock) -> None:
        from content_ingestion.infrastructure.scheduler.scheduler_process import SchedulerProcess

        mock_engine = MagicMock()
        mock_factory = MagicMock()
        mock_build.return_value = (mock_engine, mock_factory, mock_factory)

        mock_uc_instance = AsyncMock()
        mock_uc_instance.execute.side_effect = RuntimeError("db down")
        mock_uc_cls.return_value = mock_uc_instance

        settings = _make_settings()
        process = SchedulerProcess(settings=settings)

        # Should not raise — error is logged
        await process._tick()
