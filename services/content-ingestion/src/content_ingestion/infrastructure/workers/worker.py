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
import contextlib
import signal
from typing import TYPE_CHECKING

import httpx

from content_ingestion.application.use_cases.claim_tasks import ClaimTasksUseCase
from content_ingestion.application.use_cases.execute_task import ExecuteContentTaskUseCase
from content_ingestion.application.use_cases.fetch_and_write_prediction_markets import (
    FetchAndWritePredictionMarketsUseCase,
)
from content_ingestion.config import Settings
from content_ingestion.domain.entities import SourceType
from content_ingestion.domain.exceptions import AdapterError
from content_ingestion.infrastructure.adapters.polymarket.adapter import PolymarketAdapter
from content_ingestion.infrastructure.adapters.polymarket.client import PolymarketClient
from content_ingestion.infrastructure.db.repositories.adapter_state import AdapterStateRepository
from content_ingestion.infrastructure.db.repositories.fetch_log import FetchLogRepository
from content_ingestion.infrastructure.db.repositories.outbox import OutboxRepository
from content_ingestion.infrastructure.db.repositories.prediction_market_fetch_log import (
    PredictionMarketFetchLogRepository,
)
from content_ingestion.infrastructure.db.repositories.task import TaskRepository
from content_ingestion.infrastructure.db.session import _build_factories
from content_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork
from content_ingestion.infrastructure.metrics.poller import _metrics_poller
from content_ingestion.infrastructure.metrics.prometheus import record_fetch
from content_ingestion.infrastructure.scheduler.scheduler import ADAPTER_REGISTRY
from content_ingestion.infrastructure.storage.minio_bronze import MinioBronzeAdapter
from messaging.pg.advisory_lock import pg_advisory_lock  # type: ignore[import-untyped]
from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]
from observability.logging import get_logger  # type: ignore[import-untyped]
from storage.factory import build_object_storage  # type: ignore[import-untyped]
from storage.settings import StorageSettings  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from content_ingestion.application.ports.source_adapter import SourceAdapterPort
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
        # D-04: Polymarket tasks require a longer timeout (paginated API + MinIO writes)
        self._polymarket_task_timeout = settings.worker_polymarket_task_timeout_seconds

        # Build own infrastructure (one instance per worker process — R22)
        _, _, self._write_factory, self._read_factory = _build_factories(settings)
        self._valkey = create_valkey_client_from_url(settings.valkey_url)

        # Shared EODHD quota counter (blind-spot fix, 2026-07-01). S4 is the
        # largest EODHD consumer but previously wrote no quota keys, so the
        # account-wide monthly total undercounted true usage. Every EODHD
        # request now increments the SAME Valkey counters market-ingestion (S2)
        # uses, via the shared EodhdQuotaService. Best-effort — a Valkey failure
        # never breaks ingestion (see EodhdQuotaService.record_usage).
        from messaging.eodhd_quota.quota_service import EodhdQuotaService

        self._eodhd_quota_service = EodhdQuotaService(
            valkey=self._valkey,
            hard_limit=settings.eodhd_monthly_quota,
            # EODHD's REAL cap is per-UTC-day — this is what actually blocks.
            daily_hard_limit=settings.eodhd_daily_quota,
        )

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

            # Start the periodic gauge updater (outbox-pending + DLQ counts).
            # WHY here (not app.py): R22 — background tasks live in the worker
            # process, not the FastAPI lifespan. The poller silently swallows
            # DB errors so a transient blip does not kill the worker loop.
            metrics_task = asyncio.create_task(
                _metrics_poller(
                    self._write_factory,
                    interval=self._settings.outbox_metrics_poll_seconds,
                ),
            )

            while not self._stop_event.is_set():
                # WHY try/except here: an unhandled exception in _claim_batch or
                # asyncio.gather would silently kill the worker loop — the container
                # stays up (exit code 0) but ingestion stops completely.  Catching
                # at the loop level ensures transient errors (DB blip, OOM in a
                # single task) cause a short pause + retry rather than a silent death.
                # CancelledError must be re-raised so SIGTERM / task cancellation
                # still propagates correctly (the worker's stop() sets _stop_event,
                # but the async framework also cancels the coroutine).
                try:
                    claimed = await self._claim_batch()
                    if not claimed:
                        await asyncio.sleep(self._idle_sleep)
                        continue
                    await asyncio.gather(*[self._execute_with_semaphore(task) for task in claimed])
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("worker_loop_error", worker_id=self._worker_id)
                    await asyncio.sleep(5)

            logger.info("worker_stopped", worker_id=self._worker_id)

            # Stop the gauge poller. We cancel + await it so any in-flight
            # DB query gets a chance to unwind before the write-factory closes.
            metrics_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await metrics_task

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

        D-04: Polymarket tasks use a dedicated, longer timeout because they
        paginate the entire Gamma API catalogue and write to MinIO.
        """
        timeout = self._polymarket_task_timeout if task.source_type == SourceType.POLYMARKET else self._task_timeout
        async with self._semaphore:
            try:
                async with asyncio.timeout(timeout):
                    await self._execute_task(task)
            except TimeoutError:
                logger.warning(
                    "worker_task_timeout",
                    task_id=str(task.id),
                    worker_id=self._worker_id,
                    timeout=timeout,
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

        Routes POLYMARKET tasks to the prediction-market-specific pipeline;
        all other source types use the standard FetchAndWriteUseCase path.

        Infrastructure concerns (metrics recording, adapter client
        construction) are handled here in the infra layer, keeping the
        use case free of infrastructure imports (R25).
        """
        if task.source_type == SourceType.POLYMARKET:
            await self._execute_polymarket_task(task)
            return

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
                # BP-XXX: when the session is poisoned (e.g. "Can't reconnect until
                # invalid transaction is rolled back"), rollback may also fail —
                # swallow that error and still attempt the rescue below so the task
                # doesn't stay stuck in CLAIMED state until lease expiry.
                # SIM105: contextlib.suppress is the idiomatic form for intentional swallow.
                # WHY suppress rollback errors: if the session is poisoned (e.g. "Can't
                # reconnect until invalid transaction is rolled back") the rollback call
                # itself raises. We still need to attempt the rescue path below so the
                # task doesn't stay stuck in CLAIMED state until lease expiry.
                with contextlib.suppress(Exception):
                    await session.rollback()
                logger.error(
                    "worker_task_error",
                    task_id=str(task.id),
                    error=str(exc),
                    worker_id=self._worker_id,
                )
                # Best-effort: update task status via a fresh connection so the task
                # doesn't stay stuck in CLAIMED for the full lease period (5-10 min).
                await self._rescue_stuck_task(task, str(exc))

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
            eodhd_client = EODHDClient(
                http_client=self._http_client,
                api_key=settings.eodhd_api_key,
                provider_cfg=settings.eodhd,
                # Shared quota accounting — record every request into the
                # cross-service Valkey counter so the account-wide total is true.
                quota_service=self._eodhd_quota_service,
            )
            # SHADOW STAGE (2026-07-01): thread the general-news firehose flags so
            # the filter-less feed can run the high-frequency EARLY-EXIT sweep in
            # parallel with the per-ticker sources. Return early — EODHDAdapter
            # takes firehose-specific kwargs the generic call below does not.
            from content_ingestion.infrastructure.adapters.eodhd.adapter import EODHDAdapter

            return EODHDAdapter(
                client=eodhd_client,
                rate_limiter=rate_limiter,
                exists_fn=exists_fn,
                firehose_enabled=settings.eodhd.general_news_firehose_enabled,
                shadow_mode=settings.eodhd.general_news_shadow_mode,
                page_size=settings.eodhd.page_size,
                max_pages=settings.eodhd.max_pages_per_cycle,
            )
        if source_type_val == "sec_edgar":
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
            # Transcripts are a paid Finnhub tier — thread the capability flag so
            # the adapter guards the (otherwise permanently-403) request. finnhub
            # takes an extra kwarg the generic construction path below does not,
            # so build + return it here (via the registry class so the adapter
            # remains swappable/spy-able like every other source type).
            return adapter_cls(  # type: ignore[call-arg]
                client=client,
                rate_limiter=rate_limiter,
                exists_fn=exists_fn,
                transcripts_enabled=settings.finnhub.transcripts_enabled,
            )
        elif source_type_val == "newsapi":
            client = NewsAPIClient(
                http_client=self._http_client,
                api_key=settings.newsapi_key,
                provider_cfg=settings.newsapi,
                valkey=self._valkey,
                daily_limit=settings.newsapi_daily_limit,
            )
        elif source_type_val == "eodhd_ticker_news":
            # PLAN-0106 C-1: EODHDTickerNewsAdapter manages its own httpx
            # client per-request (no shared client needed) and reads the API
            # key directly from settings.  Return early — no client/rate-limiter
            # plumbing required.
            from content_ingestion.infrastructure.adapters.eodhd_ticker_news.adapter import (
                EODHDTickerNewsAdapter,
            )

            # Per-ticker news is the DOMINANT EODHD consumer — thread the shared
            # quota service so each page request rolls up into the account-wide
            # counter (previously entirely unaccounted → monthly undercount).
            return EODHDTickerNewsAdapter(
                settings=settings,
                quota_service=self._eodhd_quota_service,
            )
        else:
            raise AdapterError(f"Unknown source type: {source_type_val}")

        # Build adapter — newsapi and sec_edgar do not accept `rate_limiter`.
        # WHY sec_edgar excluded (2026-05-09 fix): SECEdgarAdapter relies on
        # `provider_cfg.market_hours_interval_seconds` for its own pacing
        # (see `SECEdgarAdapter._compute_next_request_at`) and never accepts
        # a TokenBucket. Passing `rate_limiter=` raised TypeError which
        # surfaced as "got an unexpected keyword argument 'rate_limiter'"
        # and put every freshly-seeded SEC EDGAR task into FAILED.
        if source_type_val == "sec_edgar":
            # Thread provider_cfg so the adapter honours max_filings_per_cycle
            # (bounded-backfill cap) AND its market-hours pacing. Previously the
            # SEC adapter was built WITHOUT provider_cfg, so the cap defaulted and
            # (before this fix) the fetch was unbounded → reclaim loop (Issue #1/#2).
            return adapter_cls(  # type: ignore[call-arg]
                client=client,
                exists_fn=exists_fn,
                provider_cfg=settings.sec_edgar,
            )
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

    async def _rescue_stuck_task(self, task: ContentIngestionTask, error: str) -> None:
        """Mark a stuck-CLAIMED task RETRY/FAILED via a fresh DB connection.

        Called when the main session is poisoned and the normal execute() error
        handler couldn't write the final status. Without this, the task waits
        for lease expiry (typically 5-10 min) before recover_expired_leases
        reclaims it. This is a best-effort path — lease expiry remains the
        ultimate safety net if this also fails.
        """
        from contracts.enums import IngestionTaskStatus  # type: ignore[import-untyped]

        # execute() already called task.fail() which sets task.status to RETRY
        # or FAILED. Use that if set; otherwise default to RETRY.
        terminal_statuses = {IngestionTaskStatus.RETRY, IngestionTaskStatus.FAILED}
        target_status = task.status if task.status in terminal_statuses else IngestionTaskStatus.RETRY

        try:
            async with self._write_factory() as rescue_session:
                task_repo = TaskRepository(rescue_session)
                await task_repo.update_status(
                    task.id,
                    target_status,
                    error_detail=f"[rescued] {error[:200]}",
                )
                await rescue_session.commit()
                logger.info(
                    "worker_task_rescued",
                    task_id=str(task.id),
                    new_status=target_status.value,
                    worker_id=self._worker_id,
                )
        except Exception as rescue_exc:
            logger.error(
                "worker_task_rescue_failed",
                task_id=str(task.id),
                error=str(rescue_exc),
                worker_id=self._worker_id,
            )

    async def _execute_polymarket_task(self, task: ContentIngestionTask) -> None:
        """Execute a Polymarket prediction-market task through the dedicated pipeline.

        Pipeline (mirrors ExecuteContentTaskUseCase but uses prediction-market repos):
        1. Mark RUNNING.
        2. Build PolymarketAdapter with fetch_log_exists_fn from a short-lived session.
        3. Fetch from Gamma API (no session held during I/O — R24).
        4. If no results → mark SUCCEEDED.
        5. Under advisory lock: write fetch_log + outbox rows atomically; mark SUCCEEDED.
        """
        from contracts.enums import IngestionTaskStatus  # type: ignore[import-untyped]

        async with self._write_factory() as session:
            task_repo = TaskRepository(session)
            try:
                # 1. Mark RUNNING
                task.start()
                await task_repo.update_status(task.id, task.status)
                await session.commit()
            except Exception as exc:
                await session.rollback()
                logger.error("polymarket_task_start_failed", task_id=str(task.id), error=str(exc))
                return

        # 2. Build adapter with dedup function from a short-lived session
        from content_ingestion.domain.entities import Source

        source = Source(
            id=task.source_id,
            name=task.source_name,
            source_type=task.source_type,
            enabled=True,
            config={},
        )
        settings = self._settings

        async with self._write_factory() as dedup_session:
            pm_log_repo = PredictionMarketFetchLogRepository(dedup_session)
            polymarket_client = PolymarketClient(
                http_client=self._http_client,
                settings=settings.polymarket,
            )
            adapter = PolymarketAdapter(
                client=polymarket_client,
                fetch_log_exists_fn=pm_log_repo.exists_by_market_snapshot,
                settings=settings.polymarket,
                storage=self._storage,
            )

            # 3. Fetch (no session held during Gamma API I/O)
            try:
                results = await adapter.fetch(source)
            except Exception as exc:
                logger.error("polymarket_fetch_failed", task_id=str(task.id), error=str(exc))
                async with self._write_factory() as fail_session:
                    task_repo = TaskRepository(fail_session)
                    task.fail(str(exc))
                    await task_repo.update_status(task.id, task.status, error_detail=task.error_detail)
                    await fail_session.commit()
                return

        # 4. Empty results → SUCCEEDED immediately
        if not results:
            async with self._write_factory() as session:
                task_repo = TaskRepository(session)
                await task_repo.update_status(task.id, IngestionTaskStatus.SUCCEEDED)
                await session.commit()
                task.succeed()
            return

        # 5. Write under advisory lock — fetch_log + outbox atomically
        async with (
            self._write_factory() as session,
            pg_advisory_lock(session, f"s4:fetch:{task.source_name}") as acquired,
        ):
            if not acquired:
                task_repo = TaskRepository(session)
                await task_repo.update_status(task.id, IngestionTaskStatus.SUCCEEDED)
                await session.commit()
                task.succeed()
                return

            pm_log_repo_write = PredictionMarketFetchLogRepository(session)
            outbox_repo = OutboxRepository(session)
            write_use_case = FetchAndWritePredictionMarketsUseCase(
                fetch_log_repo=pm_log_repo_write,
                outbox_repo=outbox_repo,
                commit_fn=session.commit,
                rollback_fn=session.rollback,  # M-02: required to unpoison session on failure
            )
            summary = await write_use_case.execute(results, source_id=task.source_id)

            task_repo = TaskRepository(session)
            # F-302: if ALL results failed (no successful writes at all), treat the
            # task as failed so the scheduler can retry rather than silently succeed.
            if summary.failed > 0 and summary.fetched == 0:
                task.fail(f"all_{summary.failed}_markets_failed")
                await task_repo.update_status(task.id, task.status, error_detail=task.error_detail)
            else:
                await task_repo.update_status(task.id, IngestionTaskStatus.SUCCEEDED)
                task.succeed()
            await session.commit()

            record_fetch(
                task.source_name,
                fetched=summary.fetched,
                skipped=summary.skipped,
                failed=summary.failed,
                duration=summary.duration_seconds,
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
