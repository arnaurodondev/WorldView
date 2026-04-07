"""Worker process entrypoint for content-ingestion.

Claims and executes content ingestion tasks.  Each loop iteration:
  1. Claims a batch via ``ClaimTasksUseCase``.
  2. Executes each claimed task via ``ExecuteContentTaskUseCase``.
  3. Sleeps briefly if no tasks were available (back-pressure).

Usage (standalone)::

    python -m content_ingestion.infrastructure.workers.worker
"""

from __future__ import annotations

import asyncio
import signal
from typing import TYPE_CHECKING

import httpx

from content_ingestion.application.use_cases.claim_tasks import ClaimTasksUseCase
from content_ingestion.application.use_cases.execute_task import ExecuteContentTaskUseCase
from content_ingestion.config import Settings
from content_ingestion.domain.exceptions import AdapterError
from content_ingestion.infrastructure.db.repositories.adapter_state import AdapterStateRepository
from content_ingestion.infrastructure.db.repositories.fetch_log import FetchLogRepository
from content_ingestion.infrastructure.db.repositories.outbox import OutboxRepository
from content_ingestion.infrastructure.db.repositories.task import TaskRepository
from content_ingestion.infrastructure.db.session import _build_factories
from content_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork
from content_ingestion.infrastructure.metrics.prometheus import record_fetch
from content_ingestion.infrastructure.scheduler.scheduler import ADAPTER_REGISTRY
from content_ingestion.infrastructure.storage.minio_bronze import MinioBronzeAdapter
from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]
from observability.logging import get_logger  # type: ignore[import-untyped]
from storage.factory import build_object_storage  # type: ignore[import-untyped]
from storage.settings import StorageSettings  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from content_ingestion.application.ports.source_adapter import SourceAdapterPort
    from content_ingestion.domain.entities import ContentIngestionTask, SourceType

logger = get_logger(__name__)


def _normalize_endpoint(endpoint: str) -> str:
    """Ensure MinIO endpoint has an explicit HTTP(S) scheme."""
    if endpoint.startswith("http://") or endpoint.startswith("https://"):
        return endpoint
    return f"http://{endpoint}"


class WorkerProcess:
    """Long-running worker that claims and executes content ingestion tasks.

    Args:
        settings: Service configuration.
        worker_id: Unique worker identifier.  Defaults to a random ULID.
        batch_size: Number of tasks to claim per iteration.
        lease_seconds: Lease duration in seconds.
        idle_sleep_seconds: Sleep duration when no tasks are available.
    """

    def __init__(
        self,
        settings: Settings,
        worker_id: str | None = None,
        batch_size: int | None = None,
        lease_seconds: int | None = None,
        idle_sleep_seconds: float | None = None,
    ) -> None:
        import common.ids

        self._settings = settings
        self._worker_id = worker_id or common.ids.new_ulid()
        self._batch_size = batch_size if batch_size is not None else settings.worker_batch_size
        self._lease_seconds = lease_seconds if lease_seconds is not None else settings.worker_lease_seconds
        self._idle_sleep = idle_sleep_seconds if idle_sleep_seconds is not None else settings.worker_idle_sleep_seconds
        self._stop_event = asyncio.Event()
        self._semaphore = asyncio.Semaphore(settings.worker_concurrency)
        self._task_timeout = settings.worker_task_timeout_seconds

        # Build own infrastructure (one instance per worker process — R22)
        _, _, self._write_factory, self._read_factory = _build_factories(settings)
        self._valkey = create_valkey_client_from_url(settings.valkey_url)

        storage_settings = StorageSettings(
            endpoint=_normalize_endpoint(settings.minio_endpoint),
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            use_ssl=settings.minio_secure,
            default_bucket=settings.minio_bucket,
        )
        self._storage = build_object_storage(settings=storage_settings)

    def stop(self) -> None:
        """Signal the worker loop to stop after the current batch."""
        self._stop_event.set()

    async def run(self) -> None:
        """Run the worker loop until ``stop()`` is called."""
        from content_ingestion.infrastructure.http.ssrf_transport import SSRFSafeTransport

        async with httpx.AsyncClient(
            transport=SSRFSafeTransport(),
            timeout=httpx.Timeout(
                self._settings.http_client.timeout_seconds,
                connect=self._settings.http_client.connect_timeout_seconds,
            ),
        ) as http_client:
            self._http_client = http_client

            logger.info(
                "worker_starting",
                worker_id=self._worker_id,
                batch_size=self._batch_size,
                lease_seconds=self._lease_seconds,
                concurrency=self._settings.worker_concurrency,
            )
            while not self._stop_event.is_set():
                claimed = await self._claim_batch()
                if not claimed:
                    await asyncio.sleep(self._idle_sleep)
                    continue
                await asyncio.gather(*[self._execute_with_semaphore(task) for task in claimed])

            logger.info("worker_stopped", worker_id=self._worker_id)

        # Cleanup
        await self._valkey.close()

    async def _claim_batch(self) -> list[ContentIngestionTask]:
        """Claim a batch of tasks and return them."""
        uow = SqlaUnitOfWork(self._write_factory, self._read_factory)
        use_case = ClaimTasksUseCase(uow=uow)
        try:
            tasks = await use_case.execute(
                worker_id=self._worker_id,
                batch_size=self._batch_size,
                lease_seconds=self._lease_seconds,
            )
            logger.debug("worker_claimed_tasks", count=len(tasks), worker_id=self._worker_id)
            return tasks
        except Exception as exc:
            logger.error("worker_claim_error", error=str(exc), worker_id=self._worker_id)
            await asyncio.sleep(self._idle_sleep)
            return []

    async def _execute_with_semaphore(self, task: ContentIngestionTask) -> None:
        """Acquire the concurrency semaphore then execute the task.

        Semaphore is acquired first so timeout only measures actual execution.
        On timeout, the task is explicitly marked FAILED to avoid the 5-minute
        lease-expiry delay before the scheduler can recover it.
        """
        async with self._semaphore:
            try:
                async with asyncio.timeout(self._task_timeout):
                    await self._execute_task(task)
            except TimeoutError:
                logger.warning(
                    "worker_task_timeout",
                    task_id=str(task.id),
                    worker_id=self._worker_id,
                    timeout=self._task_timeout,
                )
                # Mark the task as failed immediately so the scheduler
                # doesn't have to wait for lease expiry to re-queue it.
                await self._mark_task_timed_out(task)

    async def _mark_task_timed_out(self, task: ContentIngestionTask) -> None:
        """Write FAILED/RETRY status to DB for a timed-out task.

        Opens a fresh write session (the original task session was rolled back
        by the timeout cancellation).  If the task never reached RUNNING state
        (timeout fired before task.start() completed), falls back to writing
        RETRY directly via update_status so the domain state machine is not
        violated.
        """
        from contracts.enums import IngestionTaskStatus  # type: ignore[import-untyped]

        try:
            async with self._write_factory() as session:
                task_repo = TaskRepository(session)
                new_status: IngestionTaskStatus
                if task.status == IngestionTaskStatus.RUNNING:
                    task.fail("task_timeout")  # increments attempt_count, sets RETRY or FAILED
                    new_status = task.status
                else:
                    # Task never reached RUNNING (timeout fired very early); write RETRY directly
                    new_status = IngestionTaskStatus.RETRY
                await task_repo.update_status(task.id, new_status, error_detail="task_timeout")
                await session.commit()
                logger.info(
                    "worker_task_timed_out_marked",
                    task_id=str(task.id),
                    new_status=new_status.value,
                    worker_id=self._worker_id,
                )
        except Exception as exc:
            # Best-effort — if this fails, lease expiry will recover the task
            logger.error(
                "worker_task_timeout_mark_failed",
                task_id=str(task.id),
                error=str(exc),
            )

    async def _execute_task(self, task: ContentIngestionTask) -> None:
        """Execute a single claimed task through the pipeline.

        Uses a dedicated write session for task status updates so the
        ExecuteContentTaskUseCase can manage its own sessions internally
        (R24 session optimization).

        Infrastructure concerns (metrics recording, adapter client
        construction) are handled here in the infra layer, keeping the
        use case free of infrastructure imports (R25).
        """
        bronze = MinioBronzeAdapter(self._storage)
        use_case = ExecuteContentTaskUseCase(
            write_factory=self._write_factory,
            settings=self._settings,
            bronze=bronze,
            adapter_state_factory=AdapterStateRepository,
            fetch_log_factory=FetchLogRepository,
            outbox_factory=OutboxRepository,
            adapter_builder=self._build_adapter,
            task_factory=TaskRepository,  # D-9: atomic task-status + data commit
        )
        async with self._write_factory() as session:
            task_repo = TaskRepository(session)
            try:
                summary = await use_case.execute(task, task_repo)
                await session.commit()
                # Record metrics in the infrastructure layer (R25 — T-C-05)
                if summary is not None:
                    record_fetch(
                        task.source_name,
                        fetched=summary.fetched,
                        skipped=summary.skipped,
                        failed=summary.failed,
                        duration=summary.duration_seconds,
                    )
            except Exception as exc:
                await session.rollback()
                logger.error(
                    "worker_task_error",
                    task_id=str(task.id),
                    error=str(exc),
                    worker_id=self._worker_id,
                )

    def _build_adapter(
        self,
        source_type: SourceType,
        exists_fn: Callable[[str], Awaitable[bool]],
    ) -> SourceAdapterPort:
        """Build a source adapter for the given type (infrastructure layer).

        Encapsulates client construction, rate-limiter setup, and adapter
        registry lookup — all infrastructure concerns that the use case
        delegates here via the ``adapter_builder`` callable (R25).
        """
        import common.time as ct_mod
        from content_ingestion.domain.value_objects import TokenBucket
        from content_ingestion.infrastructure.adapters.eodhd.client import EODHDClient
        from content_ingestion.infrastructure.adapters.finnhub.client import FinnhubClient
        from content_ingestion.infrastructure.adapters.newsapi.client import NewsAPIClient
        from content_ingestion.infrastructure.adapters.sec_edgar.client import SECEdgarClient

        adapter_cls = ADAPTER_REGISTRY.get(source_type)
        if adapter_cls is None:
            raise AdapterError(f"No adapter registered for source type {source_type!r}")

        now = ct_mod.utc_now()
        settings = self._settings

        # Build rate limiter and client
        eodhd_rps = settings.eodhd.rate_limit_per_second
        rate_limiter = TokenBucket(
            capacity=int(eodhd_rps),
            tokens=eodhd_rps,
            refill_rate=eodhd_rps,
            last_refill=now,
        )

        client: object
        source_type_val = source_type.value
        if source_type_val == "eodhd":
            client = EODHDClient(
                http_client=self._http_client,
                api_key=settings.eodhd_api_key,
                provider_cfg=settings.eodhd,
            )
        elif source_type_val == "sec_edgar":
            client = SECEdgarClient(
                http_client=self._http_client,
                user_agent=settings.sec_edgar_user_agent,
                provider_cfg=settings.sec_edgar,
            )
        elif source_type_val == "finnhub":
            rate_per_second = settings.finnhub.rate_limit_per_minute / 60.0
            rate_limiter = TokenBucket(
                capacity=settings.finnhub.rate_limit_per_minute,
                tokens=float(settings.finnhub.rate_limit_per_minute),
                refill_rate=rate_per_second,
                last_refill=now,
            )
            client = FinnhubClient(
                http_client=self._http_client,
                api_key=settings.finnhub_api_key,
                provider_cfg=settings.finnhub,
            )
        elif source_type_val == "newsapi":
            client = NewsAPIClient(
                http_client=self._http_client,
                api_key=settings.newsapi_key,
                provider_cfg=settings.newsapi,
                valkey=self._valkey,
                daily_limit=settings.newsapi_daily_limit,
            )
        else:
            raise AdapterError(f"Unknown source type: {source_type_val}")

        # Build adapter — newsapi does not use rate_limiter
        if source_type_val == "newsapi":
            return adapter_cls(  # type: ignore[call-arg]
                client=client,
                exists_fn=exists_fn,
            )
        return adapter_cls(  # type: ignore[call-arg]
            client=client,
            rate_limiter=rate_limiter,
            exists_fn=exists_fn,
        )


async def _run_worker() -> None:
    """Async entry-point; installs signal handlers for graceful shutdown."""
    settings = Settings()  # type: ignore[call-arg]
    worker = WorkerProcess(settings=settings)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.stop)

    await worker.run()


def main() -> None:
    """Synchronous entry-point for ``python -m content_ingestion.infrastructure.workers.worker``."""
    asyncio.run(_run_worker())


if __name__ == "__main__":
    main()
