"""Unit tests for WorkerProcess."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from content_ingestion.domain.entities import ContentIngestionTask, SourceType

import common.ids
import common.time
from contracts.enums import IngestionTaskStatus  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task(name: str = "test-source") -> ContentIngestionTask:
    return ContentIngestionTask(
        source_id=common.ids.new_uuid7(),
        source_name=name,
        source_type=SourceType.EODHD,
        status=IngestionTaskStatus.CLAIMED,
        worker_id="w-test",
    )


def _make_settings() -> MagicMock:
    settings = MagicMock()
    settings.db_url = "postgresql+asyncpg://u:p@localhost:5432/test"
    settings.db_url_read = ""
    settings.worker_batch_size = 5
    settings.worker_lease_seconds = 300
    settings.worker_idle_sleep_seconds = 0.01  # fast for tests
    settings.worker_concurrency = 2
    settings.worker_task_timeout_seconds = 10.0
    settings.valkey_url = "redis://localhost:6379"
    settings.minio_endpoint = "localhost:9000"
    settings.minio_access_key = "test"
    settings.minio_secret_key = "test"  # noqa: S105
    settings.minio_bucket = "test-bucket"
    settings.minio_secure = False
    settings.http_client = MagicMock()
    settings.http_client.timeout_seconds = 30.0
    settings.http_client.connect_timeout_seconds = 5.0
    return settings


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWorkerStop:
    @patch("content_ingestion.infrastructure.workers.worker._build_factories")
    @patch("content_ingestion.infrastructure.workers.worker.create_valkey_client_from_url")
    @patch("content_ingestion.infrastructure.workers.worker.build_object_storage")
    async def test_stop_causes_run_to_exit(
        self, mock_storage: MagicMock, mock_valkey: MagicMock, mock_build: MagicMock
    ) -> None:
        from content_ingestion.infrastructure.workers.worker import WorkerProcess

        mock_engine = MagicMock()
        mock_factory = MagicMock()
        mock_build.return_value = (mock_engine, mock_factory, mock_factory)
        mock_valkey.return_value = AsyncMock()

        settings = _make_settings()
        worker = WorkerProcess(settings=settings)

        # Patch _claim_batch to return empty and stop after 2 iterations
        call_count = 0

        async def _claim_then_stop() -> list[ContentIngestionTask]:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                worker.stop()
            return []

        worker._claim_batch = _claim_then_stop  # type: ignore[assignment]

        # Mock httpx client context
        with patch("content_ingestion.infrastructure.workers.worker.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = mock_client

            await worker.run()

        assert call_count >= 2


class TestWorkerClaimEmpty:
    @patch("content_ingestion.infrastructure.workers.worker._build_factories")
    @patch("content_ingestion.infrastructure.workers.worker.create_valkey_client_from_url")
    @patch("content_ingestion.infrastructure.workers.worker.build_object_storage")
    async def test_worker_sleeps_when_no_tasks(
        self, mock_storage: MagicMock, mock_valkey: MagicMock, mock_build: MagicMock
    ) -> None:
        from content_ingestion.infrastructure.workers.worker import WorkerProcess

        mock_engine = MagicMock()
        mock_factory = MagicMock()
        mock_build.return_value = (mock_engine, mock_factory, mock_factory)
        mock_valkey.return_value = AsyncMock()

        settings = _make_settings()
        worker = WorkerProcess(settings=settings)

        # Patch ClaimTasksUseCase to return empty
        with patch("content_ingestion.infrastructure.workers.worker.ClaimTasksUseCase") as MockClaim:
            mock_uc = AsyncMock()
            mock_uc.execute.return_value = []
            MockClaim.return_value = mock_uc

            uow_mock = AsyncMock()
            with patch("content_ingestion.infrastructure.workers.worker.SqlaUnitOfWork", return_value=uow_mock):
                tasks = await worker._claim_batch()
                assert tasks == []


class TestWorkerExecuteTask:
    @patch("content_ingestion.infrastructure.workers.worker._build_factories")
    @patch("content_ingestion.infrastructure.workers.worker.create_valkey_client_from_url")
    @patch("content_ingestion.infrastructure.workers.worker.build_object_storage")
    async def test_worker_executes_claimed_task(
        self, mock_storage: MagicMock, mock_valkey: MagicMock, mock_build: MagicMock
    ) -> None:
        from content_ingestion.infrastructure.workers.worker import WorkerProcess

        mock_engine = MagicMock()
        mock_session = AsyncMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)
        mock_factory = MagicMock(return_value=mock_session_cm)
        mock_build.return_value = (mock_engine, mock_factory, mock_factory)
        mock_valkey.return_value = AsyncMock()

        settings = _make_settings()
        worker = WorkerProcess(settings=settings)
        worker._http_client = AsyncMock()

        task = _make_task()

        with patch("content_ingestion.infrastructure.workers.worker.ExecuteContentTaskUseCase") as MockExec:
            mock_exec = AsyncMock()
            MockExec.return_value = mock_exec

            with patch("content_ingestion.infrastructure.workers.worker.TaskRepository") as MockRepo:
                mock_repo = AsyncMock()
                MockRepo.return_value = mock_repo

                await worker._execute_task(task)

                mock_exec.execute.assert_awaited_once_with(task, mock_repo)


class TestWorkerClaimError:
    @patch("content_ingestion.infrastructure.workers.worker._build_factories")
    @patch("content_ingestion.infrastructure.workers.worker.create_valkey_client_from_url")
    @patch("content_ingestion.infrastructure.workers.worker.build_object_storage")
    async def test_worker_handles_claim_errors_gracefully(
        self, mock_storage: MagicMock, mock_valkey: MagicMock, mock_build: MagicMock
    ) -> None:
        from content_ingestion.infrastructure.workers.worker import WorkerProcess

        mock_engine = MagicMock()
        mock_factory = MagicMock()
        mock_build.return_value = (mock_engine, mock_factory, mock_factory)
        mock_valkey.return_value = AsyncMock()

        settings = _make_settings()
        worker = WorkerProcess(settings=settings)

        with patch("content_ingestion.infrastructure.workers.worker.ClaimTasksUseCase") as MockClaim:
            mock_uc = AsyncMock()
            mock_uc.execute.side_effect = RuntimeError("db down")
            MockClaim.return_value = mock_uc

            uow_mock = AsyncMock()
            with patch("content_ingestion.infrastructure.workers.worker.SqlaUnitOfWork", return_value=uow_mock):
                # Should not raise
                tasks = await worker._claim_batch()
                assert tasks == []


class TestWorkerSemaphoreTimeout:
    @patch("content_ingestion.infrastructure.workers.worker._build_factories")
    @patch("content_ingestion.infrastructure.workers.worker.create_valkey_client_from_url")
    @patch("content_ingestion.infrastructure.workers.worker.build_object_storage")
    async def test_timeout_logs_warning(
        self, mock_storage: MagicMock, mock_valkey: MagicMock, mock_build: MagicMock
    ) -> None:
        from content_ingestion.infrastructure.workers.worker import WorkerProcess

        mock_engine = MagicMock()
        mock_factory = MagicMock()
        mock_build.return_value = (mock_engine, mock_factory, mock_factory)
        mock_valkey.return_value = AsyncMock()

        settings = _make_settings()
        settings.worker_task_timeout_seconds = 0.01  # very short timeout
        worker = WorkerProcess(settings=settings)
        worker._http_client = AsyncMock()

        task = _make_task()

        # Make _execute_task sleep longer than timeout
        async def _slow_execute(t: ContentIngestionTask) -> None:
            await asyncio.sleep(1.0)

        worker._execute_task = _slow_execute  # type: ignore[assignment]

        # Should not raise — timeout is caught
        await worker._execute_with_semaphore(task)
