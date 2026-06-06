"""Worker process entrypoint for market-ingestion.

Claims and executes ingestion tasks.  Each loop iteration:
  1. Claims a batch via ``ClaimTasksUseCase``.
  2. Attempts batch execution for eligible tasks (same provider+timeframe, OHLCV
     intraday, adapter supports_batch).  One HTTP call per group instead of N.
  3. Executes remaining (non-batchable) tasks individually via ``ExecuteTaskUseCase``.
  4. Sleeps briefly if no tasks were available (back-pressure).

Usage (standalone)::

    python -m market_ingestion.infrastructure.workers.worker
"""

from __future__ import annotations

import asyncio
import signal
from collections import defaultdict
from typing import TYPE_CHECKING, Any, cast

from market_ingestion.application.use_cases.claim_tasks import ClaimTasksUseCase
from market_ingestion.application.use_cases.execute_task import ExecuteTaskUseCase
from market_ingestion.config import Settings
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.infrastructure.adapters.canonical import DefaultCanonicalSerializer
from market_ingestion.infrastructure.adapters.circuit_breaker import ValkeyCircuitBreaker
from market_ingestion.infrastructure.adapters.object_store import S3ObjectStoreAdapter
from market_ingestion.infrastructure.adapters.providers import build_provider_registry
from market_ingestion.infrastructure.adapters.zero_bar_tracker import ValkeyZeroBarTracker
from market_ingestion.infrastructure.db.session import _build_factories
from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from market_ingestion.domain.entities.ingestion_task import IngestionTask
    from market_ingestion.infrastructure.adapters.providers.registry import ProviderRegistry

logger = get_logger(__name__)

_DEFAULT_BATCH_SIZE: int = 10
_DEFAULT_LEASE_SECONDS: int = 300
_IDLE_SLEEP_SECONDS: float = 5.0

# Intraday timeframes eligible for batch execution via multi-symbol endpoints.
# Must match the timeframes supported by Alpaca's ``_TIMEFRAME_MAP``.
_INTRADAY_BATCH_TFS: frozenset[str] = frozenset({"1m", "5m", "15m", "30m", "1h", "4h"})


class WorkerProcess:
    """Long-running worker that claims and executes ingestion tasks.

    Args:
    ----
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
        # Honor explicit constructor arg first (used by integration tests for
        # fast polling); otherwise read `worker_idle_sleep_seconds` from settings
        # so CI/E2E can override via env var (R12 — E2E task-progression fix);
        # fall back to the module-level production default.
        idle_sleep_value = (
            idle_sleep_seconds
            if idle_sleep_seconds is not None
            else getattr(settings, "worker_idle_sleep_seconds", _IDLE_SLEEP_SECONDS)
        )

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

        # Build Valkey-backed infrastructure once (F-007: avoid per-task connection leak)
        self._circuit_breaker = self._build_circuit_breaker()
        self._zero_bar_tracker = self._build_zero_bar_tracker()

        # Build and load the provider routing cache from env-var settings (PRD-0032).
        # Synchronous — no I/O; reloaded via POST /internal/v1/routing/reload.
        self._routing_cache = self._build_routing_cache()

    def stop(self) -> None:
        """Signal the worker loop to stop after the current batch."""
        self._stop_event.set()

    async def run(self) -> None:
        """Run the worker loop until ``stop()`` is called.

        After claiming a batch of tasks, eligible tasks are grouped and executed
        via multi-symbol batch API calls (one HTTP request per provider+timeframe
        group).  Non-eligible tasks fall back to individual execution.
        """
        logger.info(
            "worker_starting",
            worker_id=self._worker_id,
            batch_size=self._batch_size,
            lease_seconds=self._lease_seconds,
        )
        while not self._stop_event.is_set():
            # WHY try/except here: an unhandled exception escaping _claim_batch,
            # _try_batch_execute, or asyncio.gather would silently kill the worker
            # loop — the container stays up but ingestion stops completely.
            # Catching at the loop level lets transient errors (DB blip, provider
            # timeout, OOM spike) cause a short pause + retry rather than a silent
            # death.  CancelledError is re-raised so SIGTERM propagates correctly.
            try:
                claimed = await self._claim_batch()
                if not claimed:
                    await asyncio.sleep(self._idle_sleep)
                    continue

                # Try batch execution first for eligible tasks (same provider+timeframe,
                # OHLCV intraday, adapter supports_batch).
                _, remaining = await self._try_batch_execute(claimed)

                # Execute remaining tasks individually (as before).
                if remaining:
                    await asyncio.gather(*[self._execute_with_semaphore(task) for task in remaining])
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("worker_loop_error", worker_id=self._worker_id)
                await asyncio.sleep(5)

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
            circuit_breaker=self._circuit_breaker,
            zero_bar_tracker=self._zero_bar_tracker,
            routing_cache=self._routing_cache,
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

    # ── Batch execution ──────────────────────────────────────────────────────

    async def _try_batch_execute(self, tasks: list[IngestionTask]) -> tuple[list[IngestionTask], list[IngestionTask]]:
        """Attempt to batch-execute eligible tasks.

        Groups tasks by (resolved_provider, timeframe) where:
          - dataset_type == OHLCV
          - timeframe is an intraday timeframe in ``_INTRADAY_BATCH_TFS``
          - the resolved adapter ``supports_batch``

        For each eligible group, calls ``adapter.fetch_ohlcv_batch(symbols, ...)``
        once, then feeds each symbol's result through ``execute_with_prefetched_result``
        (Steps 2-5).

        Returns:
            (batch_executed, remaining) — tasks that were batch-processed and tasks
            that must be executed individually.
        """
        batch_executed: list[IngestionTask] = []
        remaining: list[IngestionTask] = []

        # Group eligible tasks by (resolved_provider, timeframe).
        # Key: (provider_value, timeframe) → list of tasks.
        groups: dict[tuple[str, str], list[IngestionTask]] = defaultdict(list)

        for task in tasks:
            # Only OHLCV intraday tasks are eligible for batch execution.
            if task.dataset_type != DatasetType.OHLCV or task.timeframe not in _INTRADAY_BATCH_TFS:
                remaining.append(task)
                continue

            # Resolve provider via the same routing logic as ExecuteTaskUseCase.
            resolved_provider = self._resolve_provider(task)
            adapter = self._registry.get(resolved_provider)

            if not adapter.supports_batch:
                remaining.append(task)
                continue

            # Task.timeframe is guaranteed non-None here (checked above).
            group_key = (resolved_provider.value, cast("str", task.timeframe))
            groups[group_key].append(task)

        # Execute each batch group.
        for (provider_val, timeframe), group_tasks in groups.items():
            provider_enum = Provider(provider_val)
            adapter = self._registry.get(provider_enum)

            symbols = [t.symbol for t in group_tasks]
            # Build a task-by-symbol index for result distribution.
            task_by_symbol: dict[str, IngestionTask] = {t.symbol: t for t in group_tasks}

            logger.info(
                "batch_execute_start",
                provider=provider_val,
                timeframe=timeframe,
                symbol_count=len(symbols),
                worker_id=self._worker_id,
            )

            try:
                # fetch_ohlcv_batch is on the concrete adapter (Alpaca), not the ABC.
                # Cast to Any to access the batch method — checked at runtime via
                # supports_batch guard above.
                batch_adapter = cast("Any", adapter)
                results_map: dict[str, Any] = await batch_adapter.fetch_ohlcv_batch(
                    symbols=symbols,
                    timeframe=timeframe,
                    start=group_tasks[0].range_start,
                    end=group_tasks[0].range_end,
                )
            except Exception as exc:
                # Batch call failed entirely — fall back to individual execution
                # for all tasks in this group so they get proper retry handling.
                logger.warning(
                    "batch_execute_failed_fallback",
                    provider=provider_val,
                    timeframe=timeframe,
                    symbol_count=len(symbols),
                    error=str(exc),
                    worker_id=self._worker_id,
                )
                remaining.extend(group_tasks)
                continue

            logger.info(
                "batch_execute_fetched",
                provider=provider_val,
                timeframe=timeframe,
                symbols_fetched=len(results_map),
                worker_id=self._worker_id,
            )

            # Distribute results back to individual tasks for Steps 2-5.
            for symbol, fetch_result in results_map.items():
                matched_task = task_by_symbol.get(symbol)
                if matched_task is None:
                    # Symbol in results but not in our task map — should not happen.
                    logger.warning("batch_result_orphan_symbol", symbol=symbol)
                    continue

                uow = SqlaUnitOfWork(self._write_factory, self._read_factory)
                use_case = ExecuteTaskUseCase(
                    uow=uow,
                    provider_registry=self._registry,
                    object_store=self._object_store,
                    serializer=self._serializer,
                    bronze_bucket=getattr(self._settings, "bronze_bucket", "market-bronze"),
                    canonical_bucket=getattr(self._settings, "canonical_bucket", "market-canonical"),
                    circuit_breaker=self._circuit_breaker,
                    zero_bar_tracker=self._zero_bar_tracker,
                    routing_cache=self._routing_cache,
                )

                try:
                    await use_case.execute_with_prefetched_result(matched_task, fetch_result)
                    batch_executed.append(matched_task)
                except Exception as exc:
                    logger.debug(
                        "batch_task_error",
                        task_id=matched_task.id,
                        symbol=symbol,
                        error=str(exc),
                        worker_id=self._worker_id,
                    )
                    # Task error handling (retry/fail) already persisted by the use case.
                    batch_executed.append(matched_task)

        return batch_executed, remaining

    def _resolve_provider(self, task: IngestionTask) -> Provider:
        """Resolve the best provider for *task* using the routing cache or static heuristic.

        Mirrors the provider routing logic at the top of ``ExecuteTaskUseCase.execute()``
        so that batch grouping uses the same provider the use case would select.
        """
        from market_ingestion.application.use_cases.execute_task import _preferred_provider
        from market_ingestion.domain.errors import ProviderUnavailable

        if self._routing_cache is not None:
            primary_str = self._routing_cache.primary_for(str(task.dataset_type), task.timeframe)
            try:
                preferred = Provider(primary_str)
                self._registry.get(preferred)  # verify registration
                return preferred
            except (ValueError, ProviderUnavailable):
                pass
        return _preferred_provider(task.dataset_type, task.timeframe, self._registry)

    def _build_routing_cache(self) -> Any | None:
        """Build and load the provider routing cache from Settings env vars.

        Returns a ProviderRoutingCache pre-loaded with the current routing rules,
        or None if the import fails (graceful degradation to static routing).
        """
        try:
            from market_ingestion.application.services.provider_routing_cache import ProviderRoutingCache

            cache = ProviderRoutingCache()
            cache.load_from_config(self._settings)  # synchronous — no I/O
            return cache
        except Exception as exc:
            logger.warning("routing_cache_build_failed", error=str(exc))
            return None

    def _build_registry(self) -> ProviderRegistry:
        timeout = getattr(self._settings, "provider_http_timeout_seconds", 30.0)
        return build_provider_registry(self._settings, http_timeout=timeout)

    def _build_circuit_breaker(self) -> ValkeyCircuitBreaker | None:
        """Build a Valkey-backed circuit breaker if Valkey is configured."""
        valkey = self._build_valkey_client()
        if valkey is None:
            return None
        return ValkeyCircuitBreaker(valkey=valkey)

    def _build_zero_bar_tracker(self) -> ValkeyZeroBarTracker | None:
        """Build a Valkey-backed zero-bar tracker if Valkey is configured."""
        valkey = self._build_valkey_client()
        if valkey is None:
            return None
        return ValkeyZeroBarTracker(valkey=valkey)

    def _build_valkey_client(self) -> Any | None:
        """Return a ValkeyClient if Valkey URL is configured, else None."""
        valkey_url = getattr(self._settings, "valkey_url", None)
        if not valkey_url:
            return None
        try:
            from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

            return ValkeyClient(url=str(valkey_url))
        except (ImportError, Exception):
            logger.warning("valkey_client_unavailable", reason="import or connection failure")
            return None

    def _build_object_store(self) -> S3ObjectStoreAdapter:
        try:
            from storage.s3_adapter import S3ObjectStorage  # type: ignore[import-untyped]
            from storage.settings import StorageSettings  # type: ignore[import-untyped]

            storage_settings = StorageSettings(
                endpoint=self._settings.storage_endpoint,
                access_key=self._settings.storage_access_key.get_secret_value(),
                secret_key=self._settings.storage_secret_key.get_secret_value(),
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
