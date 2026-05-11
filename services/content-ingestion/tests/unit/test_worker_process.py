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
        mock_build.return_value = (mock_engine, mock_engine, mock_factory, mock_factory)
        mock_valkey_instance = AsyncMock()
        mock_valkey.return_value = mock_valkey_instance

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
        # Valkey client must be closed after run() exits (F-QA-008)
        mock_valkey_instance.close.assert_called_once()


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
        mock_build.return_value = (mock_engine, mock_engine, mock_factory, mock_factory)
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
        mock_build.return_value = (mock_engine, mock_engine, mock_factory, mock_factory)
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
        mock_build.return_value = (mock_engine, mock_engine, mock_factory, mock_factory)
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
        mock_build.return_value = (mock_engine, mock_engine, mock_factory, mock_factory)
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
        worker._mark_task_timed_out = AsyncMock()  # type: ignore[method-assign]

        # Should not raise — timeout is caught
        await worker._execute_with_semaphore(task)

        # _mark_task_timed_out must be called on timeout
        worker._mark_task_timed_out.assert_awaited_once_with(task)


class TestWorkerTimeout:
    @patch("content_ingestion.infrastructure.workers.worker._build_factories")
    @patch("content_ingestion.infrastructure.workers.worker.create_valkey_client_from_url")
    @patch("content_ingestion.infrastructure.workers.worker.build_object_storage")
    @patch("content_ingestion.infrastructure.workers.worker.TaskRepository")
    async def test_timeout_marks_task_as_failed(
        self,
        mock_task_repo_cls: MagicMock,
        mock_storage: MagicMock,
        mock_valkey: MagicMock,
        mock_build: MagicMock,
    ) -> None:
        """When a RUNNING task times out, _mark_task_timed_out updates task status to RETRY/FAILED."""
        from content_ingestion.infrastructure.workers.worker import WorkerProcess

        mock_engine = MagicMock()
        mock_session = AsyncMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)
        mock_factory = MagicMock(return_value=mock_session_cm)
        mock_build.return_value = (mock_engine, mock_engine, mock_factory, mock_factory)
        mock_valkey.return_value = AsyncMock()

        mock_repo = AsyncMock()
        mock_task_repo_cls.return_value = mock_repo

        settings = _make_settings()
        worker = WorkerProcess(settings=settings)

        # Task in RUNNING state (simulate that task.start() was already called)
        task = _make_task()
        task.start()  # CLAIMED → RUNNING

        await worker._mark_task_timed_out(task)

        # Task must be in RETRY or FAILED state after marking
        assert task.status in (IngestionTaskStatus.RETRY, IngestionTaskStatus.FAILED)
        # update_status must be called with the new status and error_detail
        mock_repo.update_status.assert_awaited_once()
        call_kwargs = mock_repo.update_status.await_args
        assert call_kwargs.kwargs.get("error_detail") == "task_timeout" or (
            len(call_kwargs.args) >= 3 and call_kwargs.args[2] == "task_timeout"
        )
        # Session must be committed
        mock_session.commit.assert_awaited_once()

    @patch("content_ingestion.infrastructure.workers.worker._build_factories")
    @patch("content_ingestion.infrastructure.workers.worker.create_valkey_client_from_url")
    @patch("content_ingestion.infrastructure.workers.worker.build_object_storage")
    @patch("content_ingestion.infrastructure.workers.worker.TaskRepository")
    async def test_timeout_marks_claimed_task_as_retry(
        self,
        mock_task_repo_cls: MagicMock,
        mock_storage: MagicMock,
        mock_valkey: MagicMock,
        mock_build: MagicMock,
    ) -> None:
        """When a CLAIMED task (never reached RUNNING) times out, status is set to RETRY."""
        from content_ingestion.infrastructure.workers.worker import WorkerProcess

        from contracts.enums import IngestionTaskStatus  # type: ignore[import-untyped]

        mock_engine = MagicMock()
        mock_session = AsyncMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)
        mock_factory = MagicMock(return_value=mock_session_cm)
        mock_build.return_value = (mock_engine, mock_engine, mock_factory, mock_factory)
        mock_valkey.return_value = AsyncMock()

        mock_repo = AsyncMock()
        mock_task_repo_cls.return_value = mock_repo

        settings = _make_settings()
        worker = WorkerProcess(settings=settings)

        # Task still in CLAIMED state (task.start() never called)
        task = _make_task()
        assert task.status == IngestionTaskStatus.CLAIMED

        await worker._mark_task_timed_out(task)

        # update_status must be called with RETRY and error_detail
        mock_repo.update_status.assert_awaited_once()
        call_args = mock_repo.update_status.await_args
        # First positional arg after task_id is the new status
        new_status = call_args.args[1]
        assert new_status == IngestionTaskStatus.RETRY
        assert call_args.kwargs.get("error_detail") == "task_timeout"
        mock_session.commit.assert_awaited_once()

    @patch("content_ingestion.infrastructure.workers.worker._build_factories")
    @patch("content_ingestion.infrastructure.workers.worker.create_valkey_client_from_url")
    @patch("content_ingestion.infrastructure.workers.worker.build_object_storage")
    @patch("content_ingestion.infrastructure.workers.worker.TaskRepository")
    async def test_timeout_mark_failure_is_best_effort(
        self,
        mock_task_repo_cls: MagicMock,
        mock_storage: MagicMock,
        mock_valkey: MagicMock,
        mock_build: MagicMock,
    ) -> None:
        """If the DB write in _mark_task_timed_out fails, the error is logged and not re-raised."""
        from content_ingestion.infrastructure.workers.worker import WorkerProcess

        mock_engine = MagicMock()
        mock_session = AsyncMock()
        mock_session.commit.side_effect = RuntimeError("db write failed")
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)
        mock_factory = MagicMock(return_value=mock_session_cm)
        mock_build.return_value = (mock_engine, mock_engine, mock_factory, mock_factory)
        mock_valkey.return_value = AsyncMock()

        mock_repo = AsyncMock()
        mock_task_repo_cls.return_value = mock_repo

        settings = _make_settings()
        worker = WorkerProcess(settings=settings)

        task = _make_task()
        task.start()  # CLAIMED → RUNNING

        # Must not raise — error is best-effort
        await worker._mark_task_timed_out(task)


# ---------------------------------------------------------------------------
# WorkerProcess._build_adapter — regression for the 2026-05-09 SEC EDGAR fix
# ---------------------------------------------------------------------------


class TestBuildAdapterKwargs:
    """Validate per-source-type adapter constructor kwargs.

    Regression for the SEC-EDGAR seeding incident (2026-05-09 QA):
        SECEdgarAdapter.__init__() got an unexpected keyword argument 'rate_limiter'

    The default branch in ``_build_adapter`` previously passed ``rate_limiter=`` to
    every adapter except ``newsapi``. SEC EDGAR does not accept that kwarg
    (it does its own pacing via provider settings), so every freshly-seeded
    SEC task moved straight to FAILED. The fix groups newsapi + sec_edgar
    together; this test guards the grouping so a future refactor does not
    re-introduce the bug.
    """

    @pytest.mark.parametrize(
        ("source_type", "expects_rate_limiter"),
        [
            (SourceType.EODHD, True),
            (SourceType.FINNHUB, True),
            (SourceType.NEWSAPI, False),
            (SourceType.SEC_EDGAR, False),
        ],
    )
    @patch("content_ingestion.infrastructure.workers.worker._build_factories")
    @patch("content_ingestion.infrastructure.workers.worker.create_valkey_client_from_url")
    @patch("content_ingestion.infrastructure.workers.worker.build_object_storage")
    def test_build_adapter_passes_rate_limiter_only_when_supported(
        self,
        mock_storage: MagicMock,
        mock_valkey: MagicMock,
        mock_build: MagicMock,
        source_type: SourceType,
        expects_rate_limiter: bool,
    ) -> None:
        """Adapters that don't accept rate_limiter must NOT receive it.

        We patch the registry so adapter_cls is a MagicMock, then assert on
        whether 'rate_limiter' appeared in the kwargs.
        """
        from content_ingestion.infrastructure.workers import worker as worker_mod
        from content_ingestion.infrastructure.workers.worker import WorkerProcess

        mock_engine = MagicMock()
        mock_session_cm = AsyncMock()
        mock_factory = MagicMock(return_value=mock_session_cm)
        mock_build.return_value = (mock_engine, mock_engine, mock_factory, mock_factory)
        mock_valkey.return_value = AsyncMock()

        settings = _make_settings()
        # Provide every provider sub-config the build path may dereference.
        settings.eodhd = MagicMock(rate_limit_per_second=10)
        settings.eodhd_api_key = "demo"
        settings.finnhub = MagicMock(rate_limit_per_minute=60)
        settings.finnhub_api_key = "demo"
        settings.newsapi = MagicMock()
        settings.newsapi_key = "demo"
        settings.newsapi_daily_limit = 100
        settings.sec_edgar = MagicMock()
        settings.sec_edgar_user_agent = "test/1.0 contact@test"

        worker = WorkerProcess(settings=settings)
        # _build_adapter accesses self._http_client and self._valkey directly
        # (they are normally populated by run() before any adapter is built).
        worker._http_client = MagicMock()
        worker._valkey = AsyncMock()

        # Replace the registry entry with our spy so we can capture kwargs
        # without instantiating the real adapter (which has its own validation).
        # Also stub out the per-provider client classes — SECEdgarClient builds
        # an asyncio.Semaphore from settings.sec_edgar.max_concurrent, which
        # blows up on a MagicMock.
        adapter_spy = MagicMock(__name__=f"{source_type.value}AdapterSpy")
        original = worker_mod.ADAPTER_REGISTRY[source_type]
        worker_mod.ADAPTER_REGISTRY[source_type] = adapter_spy
        try:
            with (
                patch(
                    "content_ingestion.infrastructure.adapters.eodhd.client.EODHDClient",
                    return_value=MagicMock(),
                ),
                patch(
                    "content_ingestion.infrastructure.adapters.finnhub.client.FinnhubClient",
                    return_value=MagicMock(),
                ),
                patch(
                    "content_ingestion.infrastructure.adapters.newsapi.client.NewsAPIClient",
                    return_value=MagicMock(),
                ),
                patch(
                    "content_ingestion.infrastructure.adapters.sec_edgar.client.SECEdgarClient",
                    return_value=MagicMock(),
                ),
            ):
                worker._build_adapter(source_type, exists_fn=AsyncMock(return_value=False))
        finally:
            worker_mod.ADAPTER_REGISTRY[source_type] = original

        assert adapter_spy.called, f"adapter for {source_type.value} was never constructed"
        kwargs = adapter_spy.call_args.kwargs
        if expects_rate_limiter:
            assert "rate_limiter" in kwargs, f"{source_type.value} adapter should receive rate_limiter kwarg"
        else:
            assert "rate_limiter" not in kwargs, (
                f"{source_type.value} adapter must NOT receive rate_limiter "
                f"(its __init__ does not accept it; passing it triggers TypeError)"
            )
