"""Scheduler process entrypoint for content-ingestion.

Runs on a configurable interval and calls ``ScheduleDueSourcesUseCase``
on each tick to enqueue tasks for all enabled sources.

Usage (standalone)::

    python -m content_ingestion.infrastructure.scheduler.scheduler_main
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from contextlib import suppress

import common.time  # type: ignore[import-untyped]
from content_ingestion.application.use_cases.schedule_sources import ScheduleDueSourcesUseCase
from content_ingestion.config import Settings
from content_ingestion.infrastructure.db.session import _build_factories
from content_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork
from observability import log_runtime_banner, start_metrics_server  # type: ignore[import-untyped]
from observability.logging import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)


class SchedulerProcess:
    """Tick-based scheduler that periodically enqueues content ingestion tasks.

    Args:
        settings: Service configuration.
        tick_interval_seconds: Time between scheduler ticks in seconds.
        max_tasks_per_tick: Cap on tasks enqueued per tick.
    """

    def __init__(
        self,
        settings: Settings,
        tick_interval_seconds: float | None = None,
        max_tasks_per_tick: int | None = None,
    ) -> None:
        self._settings = settings
        self._tick_interval = tick_interval_seconds or settings.scheduler_tick_interval_seconds
        self._max_tasks_per_tick = max_tasks_per_tick or settings.scheduler_max_tasks_per_tick
        self._stop_event = asyncio.Event()
        _, _, self._write_factory, self._read_factory = _build_factories(settings)

    def stop(self) -> None:
        """Signal the scheduler loop to stop after the current tick."""
        self._stop_event.set()
        # PLAN-0106 C-2: also tear down the ticker-news sync worker when the
        # scheduler receives SIGTERM so both loops exit cleanly together.
        worker = getattr(self, "_ticker_news_sync_worker", None)
        if worker is not None:
            worker.stop()

    async def run(self) -> None:
        """Run the scheduler loop until ``stop()`` is called."""
        logger.info(
            "scheduler_starting",
            tick_interval_seconds=self._tick_interval,
            max_tasks_per_tick=self._max_tasks_per_tick,
        )

        # PLAN-0106 B-1: advisory warning at startup for any configured source
        # whose provider API key is missing from the environment.  Non-fatal —
        # the scheduler continues; sources that lack keys will produce HTTP 401
        # errors at fetch time and land in RETRY/FAILED.
        self._warn_on_missing_api_keys()

        # PLAN-0106 C-2: spawn the TickerNewsSymbolSyncWorker as a fire-and-
        # forget background task alongside the scheduler tick loop.  Gated by
        # ``ticker_news_sync_enabled`` (default ON) so operators retain a
        # kill-switch via the env var.
        if getattr(self._settings, "ticker_news_sync_enabled", True):
            self._spawn_ticker_news_sync()

        # PLAN-0055 B-1: one-shot config-drift detection at startup. WARNs (does
        # not fail) for any source whose live config_hash differs from the snapshot
        # at the last successful fetch — informational, not load-bearing.
        await self._warn_on_config_drift()

        while not self._stop_event.is_set():
            await self._tick()
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._tick_interval,
                )

        logger.info("scheduler_stopped")

    async def _warn_on_config_drift(self) -> None:
        """Surface sources where ``last_run_config_hash`` differs from live ``config_hash``.

        Best-effort; any failure logs at debug and the scheduler continues.
        """
        from sqlalchemy import text

        try:
            async with self._read_factory() as session:
                rows = (
                    await session.execute(
                        text(
                            """
                            SELECT s.id, s.name, sas.last_run_config_hash, s.config_hash
                            FROM sources s
                            JOIN source_adapter_state sas ON sas.source_id = s.id
                            WHERE sas.last_run_config_hash IS NOT NULL
                              AND sas.last_run_config_hash <> s.config_hash
                            """
                        )
                    )
                ).all()
            for row in rows:
                logger.warning(
                    "config_drift_detected",
                    source_id=str(row.id),
                    name=row.name,
                    last_run_hash=row.last_run_config_hash,
                    current_hash=row.config_hash,
                    detail="last_watermark may refer to old config; consider re-backfill",
                )
        except Exception as exc:
            logger.debug("config_drift_check_skipped", error=str(exc))

    async def _tick(self) -> None:
        """Execute one scheduler tick.

        Recovery runs first so that sources blocked by crashed workers are
        unblocked before the scheduling pass evaluates them.
        """
        now = common.time.utc_now()

        # 1. Three-pass watchdog: recover expired leases, unblock orphan pending
        #    rows, and hard-DLQ anything stuck past the configured hard cap.
        #    Replaces the single-pass ``recover_expired_leases`` call (which
        #    completely missed the 626 orphan PENDING rows with no lease).
        try:
            uow_recover = SqlaUnitOfWork(self._write_factory, self._read_factory)
            async with uow_recover:
                sweep = await uow_recover.tasks.recover_stale_tasks(
                    now,
                    lease_timeout_seconds=self._settings.worker_lease_seconds,
                    pending_max_age_seconds=self._settings.watchdog_pending_max_age_seconds,
                    dlq_max_age_seconds=self._settings.watchdog_dlq_max_age_seconds,
                )
                await uow_recover.commit()
            if sweep["leases_recovered"]:
                logger.warning(
                    "scheduler_leases_recovered",
                    count=sweep["leases_recovered"],
                    lease_timeout_seconds=self._settings.worker_lease_seconds,
                )
            if sweep["orphans_reset"]:
                logger.warning(
                    "scheduler_orphans_reset",
                    count=sweep["orphans_reset"],
                    pending_max_age_seconds=self._settings.watchdog_pending_max_age_seconds,
                )
            if sweep["dlq_moved"]:
                logger.warning(
                    "scheduler_watchdog_dlq",
                    count=sweep["dlq_moved"],
                    dlq_max_age_seconds=self._settings.watchdog_dlq_max_age_seconds,
                )
        except Exception as exc:
            logger.error("scheduler_lease_recovery_error", error=str(exc))

        # 2. Evaluate sources and enqueue new tasks.
        #
        # BP-460: inject per-source-type interval overrides so rate-limited
        # providers (NewsAPI: 100 req/day free tier) are not polled at the
        # global tick cadence.  The override is read from provider settings so
        # it remains configurable via env vars without touching this file.
        from content_ingestion.domain.entities import SourceType

        source_type_intervals: dict[SourceType, float] = {
            SourceType.NEWSAPI: float(self._settings.newsapi.poll_interval_seconds),
            # OPT-5 (2026-06-15): EODHD per-ticker news (5 credits/request, ~600
            # enabled sources) was ~94% of the EODHD daily quota at the global
            # tick cadence. Poll it hourly instead so fundamentals/OHLCV/new
            # policies have headroom. See EODHDProviderSettings.
            SourceType.EODHD_TICKER_NEWS: float(self._settings.eodhd.ticker_news_poll_interval_seconds),
        }

        # SHADOW STAGE (2026-07-01): when the general-news firehose is enabled,
        # override the general ``eodhd`` source's cadence so the EARLY-EXIT sweep
        # can poll at high frequency (dial ``general_news_poll_interval_seconds``
        # to 60 once the shadow run looks healthy). Early-exit pins each poll to
        # ONE request, so a 60s cadence costs ~7.2k credits/day. Gated on the flag
        # so the default keeps the general feed at the conservative global cadence.
        if self._settings.eodhd.general_news_firehose_enabled:
            source_type_intervals[SourceType.EODHD] = float(self._settings.eodhd.general_news_poll_interval_seconds)

        uow = SqlaUnitOfWork(self._write_factory, self._read_factory)
        use_case = ScheduleDueSourcesUseCase(
            uow=uow,
            scheduler_interval_seconds=self._settings.scheduler_interval_seconds,
            max_tasks_per_tick=self._max_tasks_per_tick,
            source_type_intervals=source_type_intervals,
        )
        try:
            result = await use_case.execute()
            logger.info(
                "scheduler_tick",
                tasks_enqueued=result.tasks_enqueued,
                sources_evaluated=result.sources_evaluated,
            )
        except Exception as exc:
            logger.error("scheduler_tick_error", error=str(exc))

    def _warn_on_missing_api_keys(self) -> None:
        """Log advisory warnings for any provider whose API key is not set.

        PLAN-0106 B-1 — called once at startup, before the first tick.
        Non-fatal: the scheduler continues; sources whose keys are absent will
        produce HTTP 401/403 errors at fetch time and land in RETRY/FAILED.

        Provider → settings attribute mapping:
          - eodhd        → settings.eodhd_api_key
          - finnhub      → settings.finnhub_api_key
          - newsapi      → settings.newsapi_key
          - sec_edgar    → (no key required — uses User-Agent only)
          - polymarket   → (no key required — public Gamma API)
        """
        providers_to_check = [
            ("eodhd", "eodhd_api_key"),
            ("finnhub", "finnhub_api_key"),
            ("newsapi", "newsapi_key"),
        ]
        for source_type, field_name in providers_to_check:
            raw = getattr(self._settings, field_name, "")
            # SecretStr-or-plain-str compatibility — config.py declares these as
            # plain ``str`` fields, but a future migration may switch to SecretStr.
            if hasattr(raw, "get_secret_value"):
                raw = raw.get_secret_value()
            if not raw:
                logger.warning(
                    "source_api_key_missing",
                    source_type=source_type,
                    settings_field=field_name,
                    hint=f"set the corresponding env var (e.g. CONTENT_INGESTION_{field_name.upper()})",
                )

    def _spawn_ticker_news_sync(self) -> None:
        """Detach the TickerNewsSymbolSyncWorker on a background asyncio task.

        PLAN-0106 C-2 — mirrors the ``_spawn_fundamentals_refresh`` pattern in
        market-ingestion's SchedulerProcess.  The worker's 6-hour loop runs
        concurrently with the scheduler tick loop and is torn down cleanly when
        ``stop()`` propagates via the worker's own ``stop()`` call.

        The task handle is stashed on ``self`` so it is not garbage-collected
        before the event loop ends (RUF006 guard).
        """
        from content_ingestion.infrastructure.workers.ticker_news_sync_worker import (
            TickerNewsSymbolSyncWorker,
        )

        worker = TickerNewsSymbolSyncWorker(settings=self._settings)
        # Stash so stop() can call worker.stop() on SIGTERM.
        self._ticker_news_sync_worker = worker
        self._ticker_news_sync_task: asyncio.Task[None] = asyncio.create_task(
            worker.run(),
            name="ticker_news_sync_worker",
        )
        logger.info("ticker_news_sync_worker_spawned")


async def _run_scheduler() -> None:
    """Async entry-point; installs signal handlers for graceful shutdown."""
    settings = Settings()  # type: ignore[call-arg]
    scheduler = SchedulerProcess(settings=settings)

    # PLAN-0107 B-3: expose Prometheus /metrics so this scheduler is scrape-able.
    metrics_handle = start_metrics_server(
        service_name="content-ingestion-scheduler",
        port=int(os.environ.get("METRICS_PORT", "9100")),
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, scheduler.stop)

    # PLAN-0107 B-4: emit single <service>_ready event after deps are wired.
    log_runtime_banner(
        "content-ingestion-scheduler",
        dependencies={
            "postgres_dsn": str(settings.db_url),
        },
    )

    try:
        await scheduler.run()
    finally:
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()


def main() -> None:
    """Synchronous entry-point for ``python -m content_ingestion.infrastructure.scheduler.scheduler_main``."""
    asyncio.run(_run_scheduler())


if __name__ == "__main__":
    main()
