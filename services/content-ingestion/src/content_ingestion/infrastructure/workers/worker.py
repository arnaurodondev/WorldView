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
from typing import TYPE_CHECKING, Any

import httpx

from content_ingestion.application.use_cases.claim_tasks import ClaimTasksUseCase
from content_ingestion.application.use_cases.emit_synthetic_prediction_document import (
    SyntheticDocumentEmitter,
)
from content_ingestion.application.use_cases.execute_task import ExecuteContentTaskUseCase
from content_ingestion.application.use_cases.fetch_and_write_prediction_markets import (
    FetchAndWritePredictionMarketsUseCase,
)
from content_ingestion.application.use_cases.seed_prediction_stream_worklists import (
    SeedPredictionStreamWorklistsUseCase,
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
from content_ingestion.infrastructure.db.repositories.source import SourceRepository
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
    from datetime import datetime

    from content_ingestion.application.ports.source_adapter import SourceAdapterPort
    from content_ingestion.domain.entities import ContentIngestionTask, PredictionMarketFetchResult

logger = get_logger(__name__)

# PLAN-0056 Wave B3 — the 4 deeper Polymarket streams route DIRECTLY (like the
# base POLYMARKET type), NOT via ADAPTER_REGISTRY. See _execute_prediction_stream_task.
_PREDICTION_STREAM_SOURCE_TYPES = frozenset(
    {
        SourceType.POLYMARKET_GAMMA_EVENTS,
        SourceType.POLYMARKET_CLOB,
        SourceType.POLYMARKET_DATA_TRADES,
        SourceType.POLYMARKET_DATA_OI,
    }
)


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
        # Polymarket + the 4 deeper prediction streams paginate external APIs and
        # write MinIO — give them the longer dedicated timeout (D-04).
        is_prediction = task.source_type == SourceType.POLYMARKET or task.source_type in _PREDICTION_STREAM_SOURCE_TYPES
        timeout = self._polymarket_task_timeout if is_prediction else self._task_timeout
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

        # PLAN-0056 QA: trades get a DEDICATED incremental+bounded path (per-market
        # cursor, rotating market window, per-market commit) to fix the 900s
        # timeout deadlock that kept prediction_market_trades stuck at 0. The
        # other three deeper streams keep the generic single-pass path.
        if task.source_type == SourceType.POLYMARKET_DATA_TRADES:
            await self._execute_trades_stream_task(task)
            return

        # PLAN-0056 QA: CLOB price history gets the SAME dedicated incremental +
        # bounded path (per-market cursor, rotating market window, per-market
        # commit) to stop the ``market.prediction.history.v1`` firehose (one
        # outbox event PER datapoint x full backfill depth x every cycle) that
        # flooded the outbox and starved the FIFO dispatcher behind it.
        if task.source_type == SourceType.POLYMARKET_CLOB:
            await self._execute_history_stream_task(task)
            return

        if task.source_type in _PREDICTION_STREAM_SOURCE_TYPES:
            await self._execute_prediction_stream_task(task)
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

    def _make_dedup_exists_fn(self) -> Callable[[str, datetime], Awaitable[bool]]:
        """Return a dedup callback that opens its OWN short-lived session per check.

        R24 / S4 pool-exhaustion fix (PLAN-0056 QA): the prediction fetch adapters
        call ``fetch_log_exists_fn`` DURING a paginated Gamma/CLOB HTTP fetch that
        also performs MinIO puts. Binding the callback to a session opened via
        ``async with self._write_factory()`` around ``adapter.fetch()`` pins a
        write-pool connection for the ENTIRE fetch — the documented pool-exhaustion
        → 500 path, widened by the longer polymarket task timeout.

        This wrapper instead acquires → checks → releases a fresh short-lived
        session per dedup lookup, so NO write-pool connection is held across the
        fetch. The dedup query is a single indexed existence check, so the extra
        acquire/release per market is cheap relative to the HTTP + MinIO I/O it
        replaces holding a connection for.
        """

        async def _exists(market_id: str, snapshot_at: datetime) -> bool:
            async with self._write_factory() as check_session:
                return await PredictionMarketFetchLogRepository(check_session).exists_by_market_snapshot(
                    market_id, snapshot_at
                )

        return _exists

    async def _execute_polymarket_task(self, task: ContentIngestionTask) -> None:
        """Execute a Polymarket prediction-market task through the dedicated pipeline.

        Pipeline (mirrors ExecuteContentTaskUseCase but uses prediction-market repos):
        1. Mark RUNNING.
        2. Build PolymarketAdapter with a session-per-check dedup callback.
        3. Fetch from Gamma API (NO session held during I/O — R24; the dedup
           callback opens+closes its own short-lived session per check).
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

        # NO write session is held here: the dedup callback opens+closes its own
        # short-lived session per check (R24), so no connection is pinned across
        # the paginated Gamma API fetch + MinIO puts inside adapter.fetch().
        polymarket_client = PolymarketClient(
            http_client=self._http_client,
            settings=settings.polymarket,
        )
        adapter = PolymarketAdapter(
            client=polymarket_client,
            fetch_log_exists_fn=self._make_dedup_exists_fn(),
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

        # PLAN-0056 B2: emit synthetic entity-linking documents for each market.
        # Runs OUTSIDE the snapshot advisory lock in its own session — the
        # synthetic document is a distinct atomic unit (own fetch_log + outbox
        # tx) and dedup is enforced by the article_fetch_log.url_hash UNIQUE
        # constraint, so a concurrent worker cannot double-emit. Best-effort:
        # a synthetic-doc failure must never fail the snapshot task.
        await self._emit_synthetic_documents(results)

        # PLAN-0056 live-QA (BUG 2): seed the deeper-stream (CLOB/trades/OI)
        # work-lists from THIS batch's open markets. The base fetch already holds
        # each market's conditionId + clobTokenIds, so we derive the
        # {condition_id, token_ids} work-list here and upsert it into the three
        # deeper-stream source configs — otherwise those adapters poll an empty
        # list forever (migration 0011 seeded them empty). Best-effort: a seeding
        # failure must never fail the snapshot task.
        await self._seed_prediction_stream_worklists(results)

    async def _seed_prediction_stream_worklists(
        self,
        results: list[PredictionMarketFetchResult],
    ) -> None:
        """Populate CLOB/trades/OI source configs from this batch's open markets.

        Runs in its own short-lived write session, AFTER the snapshot + synthetic
        docs. Strictly additive: any failure is swallowed so it can never break the
        base prediction-market ingestion it follows.
        """
        try:
            async with self._write_factory() as session:
                use_case = SeedPredictionStreamWorklistsUseCase(
                    source_repo=SourceRepository(session),
                    commit_fn=session.commit,
                    max_markets=self._settings.prediction_stream_worklist_max_markets,
                )
                await use_case.execute(results)
        except Exception as exc:
            # Never let work-list seeding break the worker loop.
            logger.error("prediction_stream_worklist_seed_failed", error=str(exc))

    async def _emit_synthetic_documents(
        self,
        results: list[PredictionMarketFetchResult],
    ) -> None:
        """Emit first-sight/resolution synthetic documents for each fetched market.

        Opens one short-lived write session shared across all markets; the
        emitter commits (or rolls back) its own transaction per document, so a
        single bad market never poisons the rest. Errors are swallowed here —
        this path is strictly additive to the snapshot ingestion it follows.
        """
        try:
            async with self._write_factory() as session:
                emitter = SyntheticDocumentEmitter(
                    fetch_log_repo=FetchLogRepository(session),
                    outbox_repo=OutboxRepository(session),
                    commit_fn=session.commit,
                    rollback_fn=session.rollback,
                )
                total_emitted = 0
                for result in results:
                    summary = await emitter.emit(result)
                    total_emitted += summary.emitted
                if total_emitted:
                    logger.info("synthetic_documents_cycle", emitted=total_emitted, markets=len(results))
        except Exception as exc:
            # Never let synthetic-doc emission break the worker loop.
            logger.error("synthetic_documents_emit_cycle_failed", error=str(exc))

    # ── PLAN-0056 Wave B3 — deeper Polymarket streams ─────────────────────────

    def _build_prediction_stream_adapter(
        self,
        source_type: SourceType,
        dedup_fn: Callable[[str, Any], Awaitable[bool]],
    ) -> Any:
        """Build the adapter for one deeper-stream source type (infra layer, R25).

        Each adapter reads its parent config (the ``markets`` work-list for CLOB /
        trades — PLAN-0056 Wave B4 — or ``condition_ids`` for OI) from
        ``source.config`` at ``fetch()`` time.  The CLOB / trades adapters
        get their backfill window from the flat ``polymarket_history_backfill_days``
        / ``polymarket_trades_backfill_days`` settings (threaded via ``model_copy``
        so the flat env var is authoritative over the nested default).
        """
        from content_ingestion.infrastructure.adapters.polymarket_clob.adapter import PolymarketClobHistoryAdapter
        from content_ingestion.infrastructure.adapters.polymarket_clob.client import PolymarketClobHistoryClient
        from content_ingestion.infrastructure.adapters.polymarket_data_oi.adapter import PolymarketOIAdapter
        from content_ingestion.infrastructure.adapters.polymarket_data_oi.client import PolymarketOIClient
        from content_ingestion.infrastructure.adapters.polymarket_data_trades.adapter import PolymarketTradesAdapter
        from content_ingestion.infrastructure.adapters.polymarket_data_trades.client import PolymarketTradesClient
        from content_ingestion.infrastructure.adapters.polymarket_gamma_events.adapter import PolymarketEventsAdapter
        from content_ingestion.infrastructure.adapters.polymarket_gamma_events.client import PolymarketEventsClient

        s = self._settings
        http = self._http_client
        if source_type == SourceType.POLYMARKET_GAMMA_EVENTS:
            return PolymarketEventsAdapter(
                client=PolymarketEventsClient(http_client=http, settings=s.polymarket_events),
                fetch_log_exists_fn=dedup_fn,
                settings=s.polymarket_events,
                storage=self._storage,
            )
        if source_type == SourceType.POLYMARKET_CLOB:
            clob_settings = s.polymarket_clob.model_copy(update={"backfill_days": s.polymarket_history_backfill_days})
            return PolymarketClobHistoryAdapter(
                client=PolymarketClobHistoryClient(http_client=http, settings=clob_settings),
                fetch_log_exists_fn=dedup_fn,
                settings=clob_settings,
                storage=self._storage,
            )
        if source_type == SourceType.POLYMARKET_DATA_TRADES:
            trades_settings = s.polymarket_trades.model_copy(
                update={"backfill_days": s.polymarket_trades_backfill_days}
            )
            return PolymarketTradesAdapter(
                client=PolymarketTradesClient(http_client=http, settings=trades_settings),
                fetch_log_exists_fn=dedup_fn,
                settings=trades_settings,
                storage=self._storage,
            )
        # POLYMARKET_DATA_OI
        return PolymarketOIAdapter(
            client=PolymarketOIClient(http_client=http, settings=s.polymarket_oi),
            fetch_log_exists_fn=dedup_fn,
            settings=s.polymarket_oi,
            storage=self._storage,
        )

    @staticmethod
    def _prediction_stream_spec(source_type: SourceType) -> Any:
        """Return the :class:`PredictionStreamSpec` for a deeper-stream source type."""
        from content_ingestion.application.use_cases.fetch_and_write_prediction_streams import (
            PREDICTION_EVENT_SPEC,
            PREDICTION_HISTORY_SPEC,
            PREDICTION_OI_SPEC,
            PREDICTION_TRADE_SPEC,
        )

        return {
            SourceType.POLYMARKET_GAMMA_EVENTS: PREDICTION_EVENT_SPEC,
            SourceType.POLYMARKET_CLOB: PREDICTION_HISTORY_SPEC,
            SourceType.POLYMARKET_DATA_TRADES: PREDICTION_TRADE_SPEC,
            SourceType.POLYMARKET_DATA_OI: PREDICTION_OI_SPEC,
        }[source_type]

    async def _execute_prediction_stream_task(self, task: ContentIngestionTask) -> None:
        """Execute a deeper Polymarket-stream task (events/CLOB/trades/OI).

        Mirrors :meth:`_execute_polymarket_task`:
        1. Mark RUNNING.
        2. Build the stream adapter + fetch (no session held during API I/O — R24).
        3. Empty results → SUCCEEDED.
        4. Under advisory lock: write fetch_log + outbox atomically; mark SUCCEEDED.

        CLOB / trades run in backfill mode when ``backfill_on_startup`` is set so
        the first cycle pulls the wider historical window (gated as required).
        """
        from content_ingestion.application.use_cases.fetch_and_write_prediction_streams import (
            FetchAndWritePredictionStreamUseCase,
        )
        from content_ingestion.domain.entities import Source
        from contracts.enums import IngestionTaskStatus  # type: ignore[import-untyped]

        # 1. Mark RUNNING.
        async with self._write_factory() as session:
            task_repo = TaskRepository(session)
            try:
                task.start()
                await task_repo.update_status(task.id, task.status)
                await session.commit()
            except Exception as exc:
                await session.rollback()
                logger.error("prediction_stream_task_start_failed", task_id=str(task.id), error=str(exc))
                return

        spec = self._prediction_stream_spec(task.source_type)
        # Only CLOB / trades honour a backfill window; the flag is a no-op for
        # events / OI (their adapters ignore ``is_backfill``).
        is_backfill = self._settings.backfill_on_startup

        # 2. Load source config, then build adapter + fetch with NO session held.
        #    First open a SHORT-LIVED session only to read the live source config
        #    (the CLOB / trades / OI adapters read their ``markets`` work-list /
        #    ``condition_ids`` seeded on the source row), then CLOSE it before any
        #    I/O. The dedup callback opens+closes its own short-lived session per
        #    check (R24), so no write-pool connection is pinned across the fetch.
        from content_ingestion.infrastructure.db.repositories.source import SourceRepository

        async with self._write_factory() as config_session:
            source_model = await SourceRepository(config_session).get_by_id(task.source_id)
            source_config = dict(source_model.config) if source_model and source_model.config else {}
        source = Source(
            id=task.source_id,
            name=task.source_name,
            source_type=task.source_type,
            enabled=True,
            config=source_config,
        )
        adapter = self._build_prediction_stream_adapter(task.source_type, self._make_dedup_exists_fn())
        try:
            results = await adapter.fetch(source, is_backfill=is_backfill)
        except Exception as exc:
            logger.error("prediction_stream_fetch_failed", task_id=str(task.id), error=str(exc))
            async with self._write_factory() as fail_session:
                fail_repo = TaskRepository(fail_session)
                task.fail(str(exc))
                await fail_repo.update_status(task.id, task.status, error_detail=task.error_detail)
                await fail_session.commit()
            return

        # 3. Empty results → SUCCEEDED immediately.
        if not results:
            async with self._write_factory() as session:
                task_repo = TaskRepository(session)
                await task_repo.update_status(task.id, IngestionTaskStatus.SUCCEEDED)
                await session.commit()
                task.succeed()
            return

        # 4. Write under advisory lock — fetch_log + outbox atomically.
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

            write_use_case = FetchAndWritePredictionStreamUseCase(
                fetch_log_repo=PredictionMarketFetchLogRepository(session),
                outbox_repo=OutboxRepository(session),
                spec=spec,
                commit_fn=session.commit,
                rollback_fn=session.rollback,  # M-02: unpoison session on failure
            )
            summary = await write_use_case.execute(results, source_id=task.source_id, is_backfill=is_backfill)

            task_repo = TaskRepository(session)
            # F-302 parity: if EVERY result failed, fail the task so it retries.
            if summary.failed > 0 and summary.fetched == 0:
                task.fail(f"all_{summary.failed}_{task.source_type.value}_failed")
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

    # ── PLAN-0056 QA — incremental + bounded trades stream ────────────────────

    async def _execute_trades_stream_task(self, task: ContentIngestionTask) -> None:
        """Execute the Polymarket ``/trades`` task INCREMENTALLY and BOUNDED.

        ROOT CAUSE (fixed here): the generic single-pass path re-fetched the FULL
        trade history (offset 0 → ~3500) for EVERY work-list market EVERY cycle
        with a per-trade MinIO put + one final commit. With ~100 markets that blew
        even the 900s Polymarket timeout → RETRY → restart from market 1 → nothing
        committed → the cursor never bootstrapped → 0 trades EVER persisted.

        This path instead:
        1. Marks RUNNING.
        2. Reads the ``markets`` work-list + persisted ``trade_cursors`` +
           ``trades_market_offset`` from ``sources.config`` (short session, closed
           before I/O — R24).
        3. Processes a ROTATING WINDOW of ``markets_per_cycle`` markets (round-robin
           via ``trades_market_offset``) so one task fits comfortably under 900s.
        4. Per market: fetches ONLY NEW trades since the cursor (bounded by the
           trade cap), writes them under the ``s4:fetch`` advisory lock (the use
           case commits per trade — R8 outbox), then COMMITS the advanced cursor +
           rotation offset. A timeout after market K leaves markets 1..K's trades
           AND cursors durably committed and resumes at K+1 next cycle.
        """
        import time as _time

        from content_ingestion.application.use_cases.fetch_and_write_prediction_streams import (
            PREDICTION_TRADE_SPEC,
            FetchAndWritePredictionStreamUseCase,
        )
        from content_ingestion.domain.entities import Source
        from content_ingestion.infrastructure.adapters.polymarket_data_trades.adapter import PolymarketTradesAdapter
        from content_ingestion.infrastructure.adapters.polymarket_data_trades.client import PolymarketTradesClient

        # SourceRepository is imported at module level (patchable in tests).

        # 1. Mark RUNNING.
        async with self._write_factory() as session:
            task_repo = TaskRepository(session)
            try:
                task.start()
                await task_repo.update_status(task.id, task.status)
                await session.commit()
            except Exception as exc:
                await session.rollback()
                logger.error("trades_stream_task_start_failed", task_id=str(task.id), error=str(exc))
                return

        # 2. Load the live source config (work-list + cursors + rotation offset).
        async with self._write_factory() as config_session:
            source_model = await SourceRepository(config_session).get_by_id(task.source_id)
            source_config = dict(source_model.config) if source_model and source_model.config else {}
        source = Source(
            id=task.source_id,
            name=task.source_name,
            source_type=task.source_type,
            enabled=True,
            config=source_config,
        )
        all_cids = PolymarketTradesAdapter._extract_condition_ids(source)
        if not all_cids:
            logger.info("trades_stream_no_markets", task_id=str(task.id), source=task.source_name)
            await self._mark_trades_task_succeeded(task)
            return

        # 3. Select the rotating per-cycle market window.
        trades_cfg = self._settings.polymarket_trades
        n = len(all_cids)
        per_cycle = min(trades_cfg.markets_per_cycle, n)
        offset = int(source_config.get("trades_market_offset", 0) or 0)
        if offset < 0 or offset >= n:
            offset = 0
        window = [all_cids[(offset + i) % n] for i in range(per_cycle)]
        cursors: dict[str, Any] = dict(source_config.get("trade_cursors") or {})

        # 4. Build the adapter (window from settings; NO session held during I/O).
        trades_settings = trades_cfg.model_copy(
            update={"backfill_days": self._settings.polymarket_trades_backfill_days}
        )
        adapter = PolymarketTradesAdapter(
            client=PolymarketTradesClient(http_client=self._http_client, settings=trades_settings),
            fetch_log_exists_fn=self._make_dedup_exists_fn(),
            settings=trades_settings,
            storage=self._storage,
        )
        is_backfill = self._settings.backfill_on_startup

        total_fetched = 0
        total_emitted = 0
        total_skipped = 0
        total_failed = 0
        markets_failed = 0
        start = _time.monotonic()

        for i, cid in enumerate(window):
            try:
                market_result = await adapter.fetch_market(cid, cursors.get(cid), is_backfill=is_backfill)
            except Exception as exc:
                # A single market's fetch error is non-fatal — advance rotation past
                # it (persist the resume offset) so the cycle keeps making progress.
                logger.error("trades_market_fetch_failed", condition_id=cid, error=str(exc))
                markets_failed += 1
                await self._persist_trades_progress(task.source_id, cid, None, (offset + i + 1) % n)
                continue

            if market_result.results:
                async with (
                    self._write_factory() as session,
                    pg_advisory_lock(session, f"s4:fetch:{task.source_name}") as acquired,
                ):
                    if acquired:
                        write_use_case = FetchAndWritePredictionStreamUseCase(
                            fetch_log_repo=PredictionMarketFetchLogRepository(session),
                            outbox_repo=OutboxRepository(session),
                            spec=PREDICTION_TRADE_SPEC,
                            commit_fn=session.commit,
                            rollback_fn=session.rollback,  # M-02: unpoison on failure
                        )
                        summary = await write_use_case.execute(
                            market_result.results, source_id=task.source_id, is_backfill=is_backfill
                        )
                        total_fetched += summary.fetched
                        total_emitted += summary.emitted
                        total_skipped += summary.skipped
                        total_failed += summary.failed

            # INCREMENTAL COMMIT: persist this market's advanced cursor + the
            # resume offset so a later timeout/retry does not re-do this market.
            await self._persist_trades_progress(task.source_id, cid, market_result.new_cursor, (offset + i + 1) % n)

        duration = _time.monotonic() - start
        record_fetch(
            task.source_name,
            fetched=total_fetched,
            skipped=total_skipped,
            failed=total_failed,
            duration=duration,
        )
        logger.info(
            "trades_stream_cycle_complete",
            task_id=str(task.id),
            markets=len(window),
            markets_failed=markets_failed,
            fetched=total_fetched,
            emitted=total_emitted,
            duration_seconds=round(duration, 3),
        )

        # 5. Final status: only fail when EVERY windowed market errored (nothing
        # written), so the scheduler retries; otherwise SUCCEEDED (partial progress
        # is already durably committed per market).
        if window and markets_failed == len(window) and total_fetched == 0:
            async with self._write_factory() as fail_session:
                fail_repo = TaskRepository(fail_session)
                task.fail(f"all_{markets_failed}_trades_markets_failed")
                await fail_repo.update_status(task.id, task.status, error_detail=task.error_detail)
                await fail_session.commit()
            return
        await self._mark_trades_task_succeeded(task)

    async def _mark_trades_task_succeeded(self, task: ContentIngestionTask) -> None:
        """Write SUCCEEDED for a trades task in a fresh short-lived session."""
        from contracts.enums import IngestionTaskStatus  # type: ignore[import-untyped]

        async with self._write_factory() as session:
            task_repo = TaskRepository(session)
            await task_repo.update_status(task.id, IngestionTaskStatus.SUCCEEDED)
            await session.commit()
            task.succeed()

    async def _persist_trades_progress(
        self,
        source_id: Any,
        condition_id: str,
        cursor: dict[str, Any] | None,
        resume_offset: int,
    ) -> None:
        """Durably commit one market's advanced cursor + the rotation offset.

        Read-modify-write on ``sources.config`` so a concurrent work-list seeder's
        ``markets`` update (and other markets' cursors) is preserved. Best-effort:
        a persist failure is logged but never fails the task — the market's trades
        are already committed and the next cycle re-fetches (deduped by the S3
        ``ON CONFLICT`` + the use-case fetch_log check).
        """
        try:
            async with self._write_factory() as session:
                repo = SourceRepository(session)
                model = await repo.get_by_id(source_id)
                if model is None:
                    return
                cfg = dict(model.config or {})
                stored_cursors = dict(cfg.get("trade_cursors") or {})
                if cursor is not None:
                    stored_cursors[condition_id] = cursor
                cfg["trade_cursors"] = stored_cursors
                cfg["trades_market_offset"] = resume_offset
                await repo.update(source_id, config=cfg)
                await session.commit()
        except Exception as exc:
            logger.error(
                "trades_progress_persist_failed",
                condition_id=condition_id,
                error=str(exc),
            )

    # ── PLAN-0056 QA — incremental + bounded CLOB history stream ──────────────

    async def _execute_history_stream_task(self, task: ContentIngestionTask) -> None:
        """Execute the Polymarket CLOB ``/prices-history`` task INCREMENTALLY.

        ROOT CAUSE (fixed here): the generic single-pass path re-fetched the FULL
        ``backfill_days`` price depth (2 weeks x hourly ≈ 336 points/token) for
        EVERY work-list token EVERY cycle, and the history payload builder emits
        ONE outbox event PER datapoint. The fetch_log dedup keyed on
        ``(token_id, fetched_at)`` never hit (``fetched_at`` advances each cycle),
        so every cycle re-emitted the entire depth for every token → millions of
        pending ``market.prediction.history.v1`` rows that starved the single
        FIFO outbox dispatcher (and behind it trades + synthetic docs).

        This path instead mirrors the trades fix (:meth:`_execute_trades_stream_task`):
        1. Marks RUNNING.
        2. Reads the ``markets`` work-list + persisted ``history_cursors`` +
           ``history_market_offset`` from ``sources.config`` (short session,
           closed before I/O — R24).
        3. Processes a ROTATING WINDOW of ``markets_per_cycle`` markets so a cycle
           emits a bounded number of events (thousands, not millions).
        4. Per market: fetches ONLY points newer than the cursor (bounded by the
           points cap), writes them under the ``s4:fetch`` advisory lock (the use
           case commits per fetch-result — R8 outbox), then COMMITS the advanced
           cursor + rotation offset so a timeout/retry resumes at the next market.
        """
        import time as _time

        from content_ingestion.application.use_cases.fetch_and_write_prediction_streams import (
            PREDICTION_HISTORY_SPEC,
            FetchAndWritePredictionStreamUseCase,
        )
        from content_ingestion.domain.entities import Source
        from content_ingestion.infrastructure.adapters.polymarket_clob.adapter import PolymarketClobHistoryAdapter
        from content_ingestion.infrastructure.adapters.polymarket_clob.client import PolymarketClobHistoryClient

        # 1. Mark RUNNING.
        async with self._write_factory() as session:
            task_repo = TaskRepository(session)
            try:
                task.start()
                await task_repo.update_status(task.id, task.status)
                await session.commit()
            except Exception as exc:
                await session.rollback()
                logger.error("history_stream_task_start_failed", task_id=str(task.id), error=str(exc))
                return

        # 2. Load the live source config (work-list + cursors + rotation offset).
        async with self._write_factory() as config_session:
            source_model = await SourceRepository(config_session).get_by_id(task.source_id)
            source_config = dict(source_model.config) if source_model and source_model.config else {}
        source = Source(
            id=task.source_id,
            name=task.source_name,
            source_type=task.source_type,
            enabled=True,
            config=source_config,
        )
        all_markets = PolymarketClobHistoryAdapter._extract_markets(source)
        if not all_markets:
            logger.info("history_stream_no_markets", task_id=str(task.id), source=task.source_name)
            await self._mark_stream_task_succeeded(task)
            return

        # 3. Select the rotating per-cycle market window.
        clob_cfg = self._settings.polymarket_clob
        n = len(all_markets)
        per_cycle = min(clob_cfg.markets_per_cycle, n)
        offset = int(source_config.get("history_market_offset", 0) or 0)
        if offset < 0 or offset >= n:
            offset = 0
        window = [all_markets[(offset + i) % n] for i in range(per_cycle)]
        cursors: dict[str, Any] = dict(source_config.get("history_cursors") or {})

        # 4. Build the adapter (window from settings; NO session held during I/O).
        clob_settings = clob_cfg.model_copy(update={"backfill_days": self._settings.polymarket_history_backfill_days})
        adapter = PolymarketClobHistoryAdapter(
            client=PolymarketClobHistoryClient(http_client=self._http_client, settings=clob_settings),
            fetch_log_exists_fn=self._make_dedup_exists_fn(),
            settings=clob_settings,
            storage=self._storage,
        )
        is_backfill = self._settings.backfill_on_startup

        total_fetched = 0
        total_emitted = 0
        total_skipped = 0
        total_failed = 0
        markets_failed = 0
        start = _time.monotonic()

        for i, market in enumerate(window):
            key = self._history_market_key(market)
            try:
                market_result = await adapter.fetch_market(market, cursors.get(key), is_backfill=is_backfill)
            except Exception as exc:
                # A single market's fetch error is non-fatal — advance rotation past
                # it (persist the resume offset) so the cycle keeps making progress.
                logger.error("history_market_fetch_failed", market_key=key, error=str(exc))
                markets_failed += 1
                await self._persist_history_progress(task.source_id, key, None, (offset + i + 1) % n)
                continue

            if market_result.results:
                async with (
                    self._write_factory() as session,
                    pg_advisory_lock(session, f"s4:fetch:{task.source_name}") as acquired,
                ):
                    if acquired:
                        write_use_case = FetchAndWritePredictionStreamUseCase(
                            fetch_log_repo=PredictionMarketFetchLogRepository(session),
                            outbox_repo=OutboxRepository(session),
                            spec=PREDICTION_HISTORY_SPEC,
                            commit_fn=session.commit,
                            rollback_fn=session.rollback,  # M-02: unpoison on failure
                        )
                        summary = await write_use_case.execute(
                            market_result.results, source_id=task.source_id, is_backfill=is_backfill
                        )
                        total_fetched += summary.fetched
                        total_emitted += summary.emitted
                        total_skipped += summary.skipped
                        total_failed += summary.failed

            # INCREMENTAL COMMIT: persist this market's advanced cursor + the
            # resume offset so a later timeout/retry does not re-do this market.
            await self._persist_history_progress(task.source_id, key, market_result.new_cursor, (offset + i + 1) % n)

        duration = _time.monotonic() - start
        record_fetch(
            task.source_name,
            fetched=total_fetched,
            skipped=total_skipped,
            failed=total_failed,
            duration=duration,
        )
        logger.info(
            "history_stream_cycle_complete",
            task_id=str(task.id),
            markets=len(window),
            markets_failed=markets_failed,
            fetched=total_fetched,
            emitted=total_emitted,
            duration_seconds=round(duration, 3),
        )

        # 5. Final status: only fail when EVERY windowed market errored (nothing
        # written), so the scheduler retries; otherwise SUCCEEDED (partial progress
        # is already durably committed per market).
        if window and markets_failed == len(window) and total_fetched == 0:
            async with self._write_factory() as fail_session:
                fail_repo = TaskRepository(fail_session)
                task.fail(f"all_{markets_failed}_history_markets_failed")
                await fail_repo.update_status(task.id, task.status, error_detail=task.error_detail)
                await fail_session.commit()
            return
        await self._mark_stream_task_succeeded(task)

    @staticmethod
    def _history_market_key(market: Any) -> str:
        """Stable per-market cursor key: the parent conditionId, or a token surrogate.

        Legacy flat-``token_ids`` work-items have no parent conditionId
        (``condition_id is None``); fall back to the joined token ids so each
        legacy market still gets its own durable cursor.
        """
        return market.condition_id or "|".join(market.token_ids)

    async def _mark_stream_task_succeeded(self, task: ContentIngestionTask) -> None:
        """Write SUCCEEDED for a deeper-stream task in a fresh short-lived session."""
        from contracts.enums import IngestionTaskStatus  # type: ignore[import-untyped]

        async with self._write_factory() as session:
            task_repo = TaskRepository(session)
            await task_repo.update_status(task.id, IngestionTaskStatus.SUCCEEDED)
            await session.commit()
            task.succeed()

    async def _persist_history_progress(
        self,
        source_id: Any,
        market_key: str,
        cursor: dict[str, Any] | None,
        resume_offset: int,
    ) -> None:
        """Durably commit one market's advanced history cursor + the rotation offset.

        Read-modify-write on ``sources.config`` so a concurrent work-list seeder's
        ``markets`` update (and other markets' cursors) is preserved. Best-effort:
        a persist failure is logged but never fails the task — the market's points
        are already committed and the next cycle re-fetches (deduped by the S3
        ``ON CONFLICT`` + the use-case fetch_log check).
        """
        try:
            async with self._write_factory() as session:
                repo = SourceRepository(session)
                model = await repo.get_by_id(source_id)
                if model is None:
                    return
                cfg = dict(model.config or {})
                stored_cursors = dict(cfg.get("history_cursors") or {})
                if cursor is not None:
                    stored_cursors[market_key] = cursor
                cfg["history_cursors"] = stored_cursors
                cfg["history_market_offset"] = resume_offset
                await repo.update(source_id, config=cfg)
                await session.commit()
        except Exception as exc:
            logger.error(
                "history_progress_persist_failed",
                market_key=market_key,
                error=str(exc),
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
