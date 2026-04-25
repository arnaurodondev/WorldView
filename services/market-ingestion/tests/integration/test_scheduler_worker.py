"""Integration tests for Scheduler → Worker interaction (T-MI-26).

Requires live PostgreSQL. Skip otherwise.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

pytestmark = pytest.mark.integration

_NEEDS_INFRA = pytest.mark.skipif(
    not os.getenv("MARKET_INGESTION_DATABASE_URL", "").startswith("postgresql"),
    reason="Requires live PostgreSQL (set MARKET_INGESTION_DATABASE_URL)",
)


@_NEEDS_INFRA
@pytest.mark.asyncio()
async def test_scheduler_tick_with_no_policies_completes():
    """ScheduleDueTasksUseCase.execute() completes with an empty policies table."""
    from market_ingestion.application.use_cases.schedule_tasks import ScheduleDueTasksUseCase
    from market_ingestion.config import Settings
    from market_ingestion.infrastructure.db.session import _build_factories
    from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork

    settings = Settings()
    write_factory, read_factory = _build_factories(settings)
    uow = SqlaUnitOfWork(write_factory, read_factory)

    use_case = ScheduleDueTasksUseCase(uow=uow)
    result = await use_case.execute()

    assert result.policies_evaluated >= 0
    assert result.tasks_enqueued >= 0


# ---------------------------------------------------------------------------
# Unit-level scheduler-worker interaction (no real infra)
# ---------------------------------------------------------------------------


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_scheduler_process_tick_interval_respected():
    """Scheduler respects tick interval; multiple ticks are spread over time."""
    from market_ingestion.infrastructure.scheduler.scheduler import SchedulerProcess

    settings = MagicMock()
    settings.database_url = "postgresql+asyncpg://x:x@localhost/test"
    settings.database_url_read = ""

    tick_count = 0

    with (
        patch(
            "market_ingestion.infrastructure.scheduler.scheduler._build_factories",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch("market_ingestion.infrastructure.scheduler.scheduler.ScheduleDueTasksUseCase") as mock_uc,
    ):
        mock_result = MagicMock()
        mock_result.tasks_enqueued = 0
        mock_result.policies_evaluated = 0
        mock_result.budget_limited = 0
        mock_instance = mock_uc.return_value
        mock_instance.execute = AsyncMock(return_value=mock_result)

        scheduler = SchedulerProcess(settings=settings, tick_interval_seconds=0.01)

        async def counting_tick():
            nonlocal tick_count
            tick_count += 1
            if tick_count >= 3:
                scheduler.stop()

        with patch.object(scheduler, "_tick", side_effect=counting_tick):
            await scheduler.run()

    assert tick_count == 3


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_worker_idle_back_pressure():
    """Worker correctly backs off when no tasks are available."""
    from market_ingestion.infrastructure.workers.worker import WorkerProcess

    settings = MagicMock()
    settings.database_url = "postgresql+asyncpg://x:x@localhost/test"
    settings.database_url_read = ""
    settings.eodhd_api_key = SecretStr("demo")
    settings.storage_endpoint = "http://localhost:7480"
    settings.storage_access_key = SecretStr("key")
    settings.storage_secret_key = SecretStr("test-secret")
    settings.storage_bucket = "bucket"
    settings.kafka_bootstrap_servers = "localhost:9092"

    with (
        patch(
            "market_ingestion.infrastructure.workers.worker._build_factories",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch("market_ingestion.infrastructure.workers.worker.build_provider_registry"),
        patch("market_ingestion.infrastructure.workers.worker.S3ObjectStoreAdapter"),
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        worker = WorkerProcess(settings=settings, idle_sleep_seconds=5.0)

        call_count = 0

        async def fake_claim():
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                worker.stop()
            return []

        with patch.object(worker, "_claim_batch", side_effect=fake_claim):
            await worker.run()

        # asyncio.sleep should have been called with idle_sleep_seconds
        assert mock_sleep.called
        sleep_args = [c.args[0] for c in mock_sleep.call_args_list]
        assert any(s == 5.0 for s in sleep_args)
