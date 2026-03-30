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
from content_ingestion.infrastructure.db.repositories.task import TaskRepository
from content_ingestion.infrastructure.db.session import _build_factories
from content_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork
from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]
from observability.logging import get_logger  # type: ignore[import-untyped]
from storage.factory import build_object_storage  # type: ignore[import-untyped]
from storage.settings import StorageSettings  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from content_ingestion.domain.entities import ContentIngestionTask

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
        _, self._write_factory, self._read_factory = _build_factories(settings)
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

        A timeout guards against indefinite blocking when all semaphore
        permits are held.
        """
        try:
            async with asyncio.timeout(self._task_timeout):
                async with self._semaphore:
                    await self._execute_task(task)
        except TimeoutError:
            logger.warning(
                "worker_task_timeout",
                task_id=str(task.id),
                worker_id=self._worker_id,
                timeout=self._task_timeout,
            )

    async def _execute_task(self, task: ContentIngestionTask) -> None:
        """Execute a single claimed task through the pipeline.

        Uses a dedicated write session for task status updates so the
        ExecuteContentTaskUseCase can manage its own sessions internally
        (R24 session optimization).
        """
        use_case = ExecuteContentTaskUseCase(
            write_factory=self._write_factory,
            http_client=self._http_client,
            storage=self._storage,
            valkey=self._valkey,
            settings=self._settings,
        )
        async with self._write_factory() as session:
            task_repo = TaskRepository(session)
            try:
                await use_case.execute(task, task_repo)
                await session.commit()
            except Exception as exc:
                await session.rollback()
                logger.error(
                    "worker_task_error",
                    task_id=str(task.id),
                    error=str(exc),
                    worker_id=self._worker_id,
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
