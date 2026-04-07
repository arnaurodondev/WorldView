"""Worker process entrypoint for market-ingestion.

Claims and executes ingestion tasks.  Each loop iteration:
  1. Claims a batch via ``ClaimTasksUseCase``.
  2. Executes each claimed task via ``ExecuteTaskUseCase``.
  3. Sleeps briefly if no tasks were available (back-pressure).

Usage (standalone)::

    python -m market_ingestion.infrastructure.workers.worker
"""

from __future__ import annotations

import asyncio
import signal
from typing import TYPE_CHECKING, Any, cast

import httpx

from market_ingestion.application.use_cases.claim_tasks import ClaimTasksUseCase
from market_ingestion.application.use_cases.execute_task import ExecuteTaskUseCase
from market_ingestion.config import Settings
from market_ingestion.infrastructure.adapters.canonical import DefaultCanonicalSerializer
from market_ingestion.infrastructure.adapters.object_store import S3ObjectStoreAdapter
from market_ingestion.infrastructure.adapters.providers.eodhd import EODHDProviderAdapter
from market_ingestion.infrastructure.adapters.providers.registry import ProviderRegistry
from market_ingestion.infrastructure.db.session import _build_factories
from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from market_ingestion.domain.entities.ingestion_task import IngestionTask

logger = get_logger(__name__)

_DEFAULT_BATCH_SIZE: int = 10
_DEFAULT_LEASE_SECONDS: int = 300
_IDLE_SLEEP_SECONDS: float = 5.0


class WorkerProcess:
    """Long-running worker that claims and executes ingestion tasks.

    Args:
        settings: Service configuration.
        worker_id: Unique worker identifier.  Defaults to a random UUID.
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
        batch_size_value = (
            batch_size
            if batch_size is not None
            else getattr(
                settings,
                "worker_batch_size",
                _DEFAULT_BATCH_SIZE,
            )
        )
        lease_seconds_value = (
            lease_seconds
            if lease_seconds is not None
            else getattr(
                settings,
                "worker_lease_seconds",
                _DEFAULT_LEASE_SECONDS,
            )
        )
        idle_sleep_value = idle_sleep_seconds if idle_sleep_seconds is not None else _IDLE_SLEEP_SECONDS

        self._settings = settings
        import common.ids

        self._worker_id = worker_id or common.ids.new_uuid7_str()
        self._batch_size = int(cast("Any", batch_size_value))
        self._lease_seconds = int(cast("Any", lease_seconds_value))
        self._idle_sleep = float(idle_sleep_value)
        self._claim_backoff: float = 0.0
        self._stop_event = asyncio.Event()
        concurrency = int(getattr(settings, "worker_concurrency", 4))
        self._semaphore = asyncio.Semaphore(concurrency)
        self._write_factory, self._read_factory = _build_factories(settings)

        # Build shared infrastructure (one instance per worker process)
        self._registry = self._build_registry()
        self._object_store = self._build_object_store()
        self._serializer = DefaultCanonicalSerializer()

    def stop(self) -> None:
        """Signal the worker loop to stop after the current batch."""
        self._stop_event.set()

    async def run(self) -> None:
        """Run the worker loop until ``stop()`` is called."""
        logger.info(
            "worker_starting",
            worker_id=self._worker_id,
            batch_size=self._batch_size,
            lease_seconds=self._lease_seconds,
        )
        while not self._stop_event.is_set():
            claimed = await self._claim_batch()
            if not claimed:
                await asyncio.sleep(self._idle_sleep)
                continue
            await asyncio.gather(*[self._execute_with_semaphore(task) for task in claimed])

        logger.info("worker_stopped", worker_id=self._worker_id)

    async def _claim_batch(self) -> list[IngestionTask]:
        """Claim a batch of tasks and return them.

        Uses exponential backoff (capped at 60 s) on repeated DB failures so a
        single bad worker does not hammer the database (M-008).
        """
        uow = SqlaUnitOfWork(self._write_factory, self._read_factory)
        use_case = ClaimTasksUseCase(uow=uow)
        try:
            tasks = await use_case.execute(
                worker_id=self._worker_id,
                batch_size=self._batch_size,
                lease_seconds=self._lease_seconds,
            )
            self._claim_backoff = 0.0
            logger.debug("worker_claimed_tasks", count=len(tasks), worker_id=self._worker_id)
            return tasks
        except Exception as exc:
            self._claim_backoff = min(self._claim_backoff * 2 + self._idle_sleep, 60.0)
            logger.error(
                "worker_claim_error",
                error=str(exc),
                worker_id=self._worker_id,
                backoff_seconds=self._claim_backoff,
            )
            await asyncio.sleep(self._claim_backoff)
            return []

    async def _execute_with_semaphore(self, task: IngestionTask) -> None:
        """Acquire the concurrency semaphore then execute the task.

        A 60-second timeout guards against indefinite blocking when all
        semaphore permits are held (M-033).  A timeout logs a warning and
        allows the worker loop to continue with other tasks rather than
        deadlocking the entire batch.
        """
        try:
            async with asyncio.timeout(60.0):
                async with self._semaphore:
                    await self._execute_task(task)
        except TimeoutError:
            logger.warning("worker.semaphore_timeout", task_id=str(task.id), worker_id=self._worker_id)

    async def _execute_task(self, task: IngestionTask) -> None:
        """Execute a single claimed task through the pipeline."""
        uow = SqlaUnitOfWork(self._write_factory, self._read_factory)
        use_case = ExecuteTaskUseCase(
            uow=uow,
            provider_registry=self._registry,
            object_store=self._object_store,
            serializer=self._serializer,
            bronze_bucket=getattr(self._settings, "bronze_bucket", "market-bronze"),
            canonical_bucket=getattr(self._settings, "canonical_bucket", "market-canonical"),
        )
        try:
            await use_case.execute(task)
        except Exception as exc:
            # Errors are already logged and persisted by ExecuteTaskUseCase
            logger.debug(
                "worker_task_error",
                task_id=task.id,
                error=str(exc),
                worker_id=self._worker_id,
            )

    def _build_registry(self) -> ProviderRegistry:
        registry = ProviderRegistry()
        timeout = getattr(self._settings, "provider_http_timeout_seconds", 30.0)
        client = httpx.AsyncClient(timeout=timeout)
        registry.register(
            EODHDProviderAdapter(
                api_key=self._settings.eodhd_api_key,
                client=client,
                base_url=self._settings.eodhd_base_url,
            )
        )
        return registry

    def _build_object_store(self) -> S3ObjectStoreAdapter:
        try:
            from storage.s3_adapter import S3ObjectStorage  # type: ignore[import-untyped]
            from storage.settings import StorageSettings  # type: ignore[import-untyped]

            storage_settings = StorageSettings(
                endpoint=self._settings.storage_endpoint,
                access_key=self._settings.storage_access_key,
                secret_key=self._settings.storage_secret_key,
            )
            storage = S3ObjectStorage(storage_settings)
        except ImportError:
            storage = None  # type: ignore[assignment]

        return S3ObjectStoreAdapter(
            storage=storage,  # type: ignore[arg-type]
            default_bucket=self._settings.storage_bucket,
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
    """Synchronous entry-point for ``python -m market_ingestion.infrastructure.workers.worker``."""
    asyncio.run(_run_worker())


if __name__ == "__main__":
    main()
