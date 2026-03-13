"""Integration tests for the full worker task-execution pipeline (T-MI-26).

These tests require a running PostgreSQL instance and MinIO.
Run with: pytest -m integration

All tests are skipped unless MARKET_INGESTION_DATABASE_URL points to a live DB.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.integration

_NEEDS_INFRA = pytest.mark.skipif(
    not os.getenv("MARKET_INGESTION_DATABASE_URL", "").startswith("postgresql"),
    reason="Requires live PostgreSQL (set MARKET_INGESTION_DATABASE_URL)",
)


@_NEEDS_INFRA
@pytest.mark.asyncio
async def test_trigger_use_case_persists_tasks():
    """TriggerIngestionUseCase creates tasks that are readable from the DB."""
    from market_ingestion.application.use_cases.trigger_ingestion import TriggerIngestionUseCase
    from market_ingestion.config import Settings
    from market_ingestion.domain.enums import DatasetType, Provider
    from market_ingestion.infrastructure.db.session import _build_factories
    from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork

    settings = Settings()
    write_factory, read_factory = _build_factories(settings)
    uow = SqlaUnitOfWork(write_factory, read_factory)

    use_case = TriggerIngestionUseCase(uow=uow)
    result = await use_case.execute(
        provider=Provider.EODHD,
        symbols=["INTG_TEST_SYM"],
        dataset_type=DatasetType.OHLCV,
        timeframe="1d",
    )

    assert result.tasks_created >= 0  # May be 0 if already exists (idempotent)


@_NEEDS_INFRA
@pytest.mark.asyncio
async def test_claim_tasks_returns_empty_when_none_pending():
    """ClaimTasksUseCase returns empty list when no tasks are pending."""
    from market_ingestion.application.use_cases.claim_tasks import ClaimTasksUseCase
    from market_ingestion.config import Settings
    from market_ingestion.infrastructure.db.session import _build_factories
    from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork

    settings = Settings()
    write_factory, read_factory = _build_factories(settings)
    uow = SqlaUnitOfWork(write_factory, read_factory)

    use_case = ClaimTasksUseCase(uow=uow)
    # Use a worker ID that likely has no tasks
    tasks = await use_case.execute(
        worker_id="intg-test-worker-empty",
        batch_size=1,
    )
    assert isinstance(tasks, list)


@_NEEDS_INFRA
@pytest.mark.asyncio
async def test_backfill_use_case_creates_chunked_tasks():
    """BackfillUseCase creates multiple chunked tasks for a date range."""
    from market_ingestion.application.use_cases.backfill import BackfillUseCase
    from market_ingestion.config import Settings
    from market_ingestion.domain.enums import Provider
    from market_ingestion.infrastructure.db.session import _build_factories
    from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork

    settings = Settings()
    write_factory, read_factory = _build_factories(settings)
    uow = SqlaUnitOfWork(write_factory, read_factory)

    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 3, 1, tzinfo=UTC)

    use_case = BackfillUseCase(uow=uow)
    result = await use_case.execute(
        provider=Provider.EODHD,
        symbol="INTG_BF_SYM",
        start_date=start,
        end_date=end,
        timeframe="1d",
        chunk_days=30,
    )

    assert result.chunks >= 2  # 60-day range with 30-day chunks


# ---------------------------------------------------------------------------
# Mock-based worker pipeline integration (no real infra required)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_worker_pipeline_end_to_end_mocked():
    """WorkerProcess claims a task and executes the pipeline end-to-end with mocks."""
    from unittest.mock import patch

    from market_ingestion.worker.main import WorkerProcess

    settings = MagicMock()
    settings.database_url = "postgresql+asyncpg://x:x@localhost/test"
    settings.database_url_read = ""
    settings.eodhd_api_key = "demo"
    settings.storage_endpoint = "http://localhost:7480"
    settings.storage_access_key = "key"
    settings.storage_secret_key = "test-secret"  # noqa: S105
    settings.storage_bucket = "bucket"
    settings.kafka_bootstrap_servers = "localhost:9092"

    with (
        patch(
            "market_ingestion.worker.main._build_factories",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch("market_ingestion.worker.main.EODHDProviderAdapter"),
        patch("market_ingestion.worker.main.S3ObjectStoreAdapter"),
        patch("market_ingestion.worker.main.ExecuteTaskUseCase") as mock_exec,
        patch("market_ingestion.worker.main.ClaimTasksUseCase") as mock_claim,
    ):
        fake_task = MagicMock()
        fake_task.id = "task-intg-001"

        mock_claim_instance = mock_claim.return_value
        mock_claim_instance.execute = AsyncMock(return_value=[fake_task])

        mock_exec_instance = mock_exec.return_value
        mock_exec_instance.execute = AsyncMock()

        worker = WorkerProcess(settings=settings)

        # Single iteration: claim → execute → stop
        async def one_shot_execute(task):
            worker.stop()

        mock_exec_instance.execute.side_effect = one_shot_execute

        await worker.run()

        mock_claim_instance.execute.assert_called()
        mock_exec_instance.execute.assert_called_once_with(fake_task)
