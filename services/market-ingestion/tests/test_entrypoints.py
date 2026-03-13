"""Tests for scheduler, worker, and dispatcher entrypoints (T-MI-24). ≥10 test functions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**overrides) -> MagicMock:
    s = MagicMock()
    s.database_url = "postgresql+asyncpg://x:x@localhost/test"
    s.database_url_read = ""
    s.eodhd_api_key = "demo"
    s.storage_endpoint = "http://localhost:7480"
    s.storage_access_key = "key"
    s.storage_secret_key = "test-secret"  # noqa: S105
    s.storage_bucket = "test-bucket"
    s.kafka_bootstrap_servers = "localhost:9092"
    s.schema_registry_url = "http://localhost:8081"
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


# ---------------------------------------------------------------------------
# SchedulerProcess
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduler_stops_immediately_when_stop_called():
    """SchedulerProcess.run() exits as soon as stop() is called."""
    from market_ingestion.scheduler.main import SchedulerProcess

    settings = _make_settings()
    with patch(
        "market_ingestion.scheduler.main._build_factories",
        return_value=(MagicMock(), MagicMock()),
    ):
        scheduler = SchedulerProcess(settings=settings, tick_interval_seconds=60.0)
        scheduler.stop()

        # With stop already set, _tick should not be called during run
        with patch.object(scheduler, "_tick", new_callable=AsyncMock) as mock_tick:
            await scheduler.run()
            mock_tick.assert_not_called()


@pytest.mark.asyncio
async def test_scheduler_calls_tick_once_before_stop():
    """SchedulerProcess runs one tick then stops."""
    from market_ingestion.scheduler.main import SchedulerProcess

    settings = _make_settings()
    call_count = 0

    with patch(
        "market_ingestion.scheduler.main._build_factories",
        return_value=(MagicMock(), MagicMock()),
    ):
        scheduler = SchedulerProcess(settings=settings, tick_interval_seconds=0.01)

        async def fake_tick():
            nonlocal call_count
            call_count += 1
            scheduler.stop()  # stop after first tick

        with patch.object(scheduler, "_tick", side_effect=fake_tick):
            await scheduler.run()

    assert call_count == 1


@pytest.mark.asyncio
async def test_scheduler_tick_uses_schedule_due_tasks_use_case():
    """SchedulerProcess._tick() calls ScheduleDueTasksUseCase.execute()."""
    from market_ingestion.scheduler.main import SchedulerProcess

    settings = _make_settings()
    mock_result = MagicMock()
    mock_result.tasks_enqueued = 5
    mock_result.policies_evaluated = 2
    mock_result.budget_limited = 0

    with (
        patch(
            "market_ingestion.scheduler.main._build_factories",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch("market_ingestion.scheduler.main.ScheduleDueTasksUseCase") as mock_use_case,
    ):
        mock_instance = mock_use_case.return_value
        mock_instance.execute = AsyncMock(return_value=mock_result)

        scheduler = SchedulerProcess(settings=settings, tick_interval_seconds=60.0)
        await scheduler._tick()

        mock_instance.execute.assert_called_once()


@pytest.mark.asyncio
async def test_scheduler_tick_error_does_not_crash():
    """SchedulerProcess._tick() swallows exceptions to keep the loop running."""
    from market_ingestion.scheduler.main import SchedulerProcess

    settings = _make_settings()

    with (
        patch(
            "market_ingestion.scheduler.main._build_factories",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch("market_ingestion.scheduler.main.ScheduleDueTasksUseCase") as mock_use_case,
    ):
        mock_instance = mock_use_case.return_value
        mock_instance.execute = AsyncMock(side_effect=RuntimeError("db gone"))

        scheduler = SchedulerProcess(settings=settings)
        # Should not raise
        await scheduler._tick()


# ---------------------------------------------------------------------------
# WorkerProcess
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_stops_immediately_when_stop_called():
    """WorkerProcess.run() exits when stop_event is set before run()."""
    from market_ingestion.worker.main import WorkerProcess

    settings = _make_settings()

    with (
        patch(
            "market_ingestion.worker.main._build_factories",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch("market_ingestion.worker.main.EODHDProviderAdapter"),
        patch("market_ingestion.worker.main.S3ObjectStoreAdapter"),
    ):
        worker = WorkerProcess(settings=settings)
        worker.stop()

        with patch.object(worker, "_claim_batch", new_callable=AsyncMock) as mock_claim:
            await worker.run()
            mock_claim.assert_not_called()


@pytest.mark.asyncio
async def test_worker_executes_claimed_tasks():
    """WorkerProcess.run() calls _execute_task for each claimed task."""
    from market_ingestion.worker.main import WorkerProcess

    settings = _make_settings()

    with (
        patch(
            "market_ingestion.worker.main._build_factories",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch("market_ingestion.worker.main.EODHDProviderAdapter"),
        patch("market_ingestion.worker.main.S3ObjectStoreAdapter"),
    ):
        worker = WorkerProcess(settings=settings)

        fake_task = MagicMock()
        executed_tasks = []

        async def fake_claim():
            return [fake_task]

        async def fake_execute(task):
            executed_tasks.append(task)
            worker.stop()  # stop after first task is executed

        with (
            patch.object(worker, "_claim_batch", side_effect=fake_claim),
            patch.object(worker, "_execute_task", side_effect=fake_execute),
        ):
            await worker.run()

    assert executed_tasks == [fake_task]


@pytest.mark.asyncio
async def test_worker_sleeps_when_no_tasks():
    """WorkerProcess sleeps when claim returns empty list."""
    from market_ingestion.worker.main import WorkerProcess

    settings = _make_settings()

    with (
        patch(
            "market_ingestion.worker.main._build_factories",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch("market_ingestion.worker.main.EODHDProviderAdapter"),
        patch("market_ingestion.worker.main.S3ObjectStoreAdapter"),
    ):
        worker = WorkerProcess(settings=settings, idle_sleep_seconds=0.001)

        call_count = 0

        async def fake_claim():
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                worker.stop()
            return []

        with patch.object(worker, "_claim_batch", side_effect=fake_claim):
            await worker.run()

    assert call_count >= 2


@pytest.mark.asyncio
async def test_worker_claim_error_continues_loop():
    """WorkerProcess._claim_batch() swallows errors and returns empty list."""
    from market_ingestion.worker.main import WorkerProcess

    settings = _make_settings()

    with (
        patch(
            "market_ingestion.worker.main._build_factories",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch("market_ingestion.worker.main.EODHDProviderAdapter"),
        patch("market_ingestion.worker.main.S3ObjectStoreAdapter"),
        patch("market_ingestion.worker.main.ClaimTasksUseCase") as mock_claim,
    ):
        mock_instance = mock_claim.return_value
        mock_instance.execute = AsyncMock(side_effect=OSError("db gone"))

        worker = WorkerProcess(settings=settings, idle_sleep_seconds=0.001)
        result = await worker._claim_batch()

    assert result == []


@pytest.mark.asyncio
async def test_worker_execute_error_does_not_crash():
    """WorkerProcess._execute_task() swallows ExecuteTaskUseCase errors."""
    from market_ingestion.worker.main import WorkerProcess

    settings = _make_settings()

    with (
        patch(
            "market_ingestion.worker.main._build_factories",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch("market_ingestion.worker.main.EODHDProviderAdapter"),
        patch("market_ingestion.worker.main.S3ObjectStoreAdapter"),
        patch("market_ingestion.worker.main.ExecuteTaskUseCase") as mock_exec,
    ):
        mock_instance = mock_exec.return_value
        mock_instance.execute = AsyncMock(side_effect=RuntimeError("pipeline exploded"))

        worker = WorkerProcess(settings=settings)
        fake_task = MagicMock()
        # Should not raise
        await worker._execute_task(fake_task)


# ---------------------------------------------------------------------------
# DispatcherProcess
# ---------------------------------------------------------------------------


def test_dispatcher_process_stop_delegates_to_dispatcher():
    """DispatcherProcess.stop() calls the underlying dispatcher's stop()."""
    from market_ingestion.messaging.dispatcher_main import DispatcherProcess

    settings = _make_settings()

    with (
        patch(
            "market_ingestion.messaging.dispatcher_main._build_factories",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch("market_ingestion.messaging.dispatcher_main.build_market_ingestion_dispatcher") as mock_build,
    ):
        mock_dispatcher = MagicMock()
        mock_dispatcher.run = AsyncMock()
        mock_build.return_value = mock_dispatcher

        process = DispatcherProcess(settings=settings)
        process.stop()

        mock_dispatcher.stop.assert_called_once()


@pytest.mark.asyncio
async def test_dispatcher_process_run_delegates_to_dispatcher():
    """DispatcherProcess.run() calls the underlying dispatcher's run()."""
    from market_ingestion.messaging.dispatcher_main import DispatcherProcess

    settings = _make_settings()

    with (
        patch(
            "market_ingestion.messaging.dispatcher_main._build_factories",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch("market_ingestion.messaging.dispatcher_main.build_market_ingestion_dispatcher") as mock_build,
    ):
        mock_dispatcher = MagicMock()
        mock_dispatcher.run = AsyncMock()
        mock_build.return_value = mock_dispatcher

        process = DispatcherProcess(settings=settings)
        await process.run()

        mock_dispatcher.run.assert_called_once()
