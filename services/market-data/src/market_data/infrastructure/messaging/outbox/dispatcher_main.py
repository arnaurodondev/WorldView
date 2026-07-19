"""Standalone dispatcher process entrypoint for market-data.

Runs ``MarketDataOutboxDispatcher`` in a loop, forwarding outbox
records to Kafka.  Intended to run as a separate container/process.

This process also hosts the **retention pruner** for
``market_data_db.ingestion_events`` — the per-event idempotency table that
grew unbounded (~1 GB / 3.7M rows) and contributed to the 2026-07-18
disk-full outage. The dispatcher is a long-lived, single-replica process with
a write session factory to the same DB, so it is the natural host for the
pruner (no new deployment required). See
``libs/messaging/kafka/maintenance/table_retention.py``.

Usage (standalone)::

    python -m market_data.infrastructure.messaging.outbox.dispatcher_main
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from datetime import timedelta

from market_data.config import Settings
from market_data.infrastructure.db.session import build_session_factory, build_write_engine
from market_data.infrastructure.messaging.outbox.dispatcher import create_dispatcher
from messaging.kafka.maintenance import (
    RetentionCleanupWorker,
    RetentionPolicy,
    build_retention_loop_coros,
)
from observability import (  # type: ignore[import-untyped]
    configure_logging,
    get_logger,
    log_runtime_banner,
    start_metrics_server,
)

logger = get_logger(__name__)


def _build_retention_workers(settings: Settings) -> list[RetentionCleanupWorker]:
    """Build the enabled market_data_db retention pruners.

    A retention window of 0 disables the pruner (returns no worker) so pruning
    can be turned off via env without a redeploy.
    """
    workers: list[RetentionCleanupWorker] = []

    # ── outbox_events: prune delivered rows only ────────────────────────────
    # market-data's own outbox has the identical status/dispatched_at schema and
    # the identical delivered-pileup failure mode as content-ingestion's — the
    # dispatcher marks rows status='delivered' (mark_dispatched) but the
    # claimable index does not cover them. Prune pre-emptively before it grows.
    if settings.outbox_retention_seconds > 0:
        workers.append(
            RetentionCleanupWorker(
                policy=RetentionPolicy(
                    table="outbox_events",
                    pk_column="id",
                    age_column="dispatched_at",
                    retention=timedelta(seconds=settings.outbox_retention_seconds),
                    # CRITICAL: only ever delete delivered rows.
                    status_column="status",
                    status_value="delivered",
                ),
                service_name="market-data",
                batch_size=settings.outbox_prune_batch_size,
                max_batches=settings.outbox_prune_max_batches,
                interval_seconds=settings.outbox_prune_interval_seconds,
            )
        )

    # ── ingestion_events: prune old idempotency rows ────────────────────────
    if settings.ingestion_events_retention_days > 0:
        workers.append(
            RetentionCleanupWorker(
                policy=RetentionPolicy(
                    table="ingestion_events",
                    pk_column="id",
                    # ``occurred_at`` (server_default now()) — always non-null.
                    age_column="occurred_at",
                    retention=timedelta(days=settings.ingestion_events_retention_days),
                ),
                service_name="market-data",
                batch_size=settings.ingestion_events_prune_batch_size,
                max_batches=settings.ingestion_events_prune_max_batches,
                interval_seconds=settings.ingestion_events_prune_interval_seconds,
            )
        )
    return workers


class DispatcherProcess:
    """Wraps ``MarketDataOutboxDispatcher`` + retention pruners with a lifecycle API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        engine = build_write_engine(settings)
        write_factory = build_session_factory(engine)
        self._dispatcher = create_dispatcher(
            settings=settings,
            session_factory=write_factory,
        )
        # ``stop_event`` coordinates a graceful shutdown of the retention loops
        # alongside the dispatcher's own stop signal.
        self._stop_event = asyncio.Event()
        self._retention_workers = _build_retention_workers(settings)
        self._retention_coros = build_retention_loop_coros(
            workers=self._retention_workers,
            session_factory=write_factory,
            stop_event=self._stop_event,
        )

    def stop(self) -> None:
        """Signal the dispatcher loop and retention loops to stop."""
        self._dispatcher.stop()
        self._stop_event.set()

    async def run(self) -> None:
        """Run the dispatcher and retention loops until ``stop()`` is called."""
        for worker in self._retention_workers:
            logger.info(
                "retention_pruner_enabled",
                table=worker.policy.table,
                retention_seconds=int(worker.policy.retention.total_seconds()),
            )
        tasks: list[asyncio.Task[None]] = [asyncio.create_task(self._dispatcher.run())]
        for coro in self._retention_coros:
            tasks.append(asyncio.create_task(coro()))
        try:
            # The dispatcher task runs until stop(); await it, then wind down the
            # retention loops (which observe the same stop_event).
            await tasks[0]
        finally:
            self._stop_event.set()
            for task in tasks[1:]:
                task.cancel()
            for task in tasks[1:]:
                with contextlib.suppress(asyncio.CancelledError):
                    await task


async def _run_dispatcher() -> None:
    """Async entry-point; installs signal handlers for graceful shutdown."""
    settings = Settings()  # type: ignore[call-arg]

    # PLAN-0107 B-4 — full logging lifecycle (worst-6 fix).
    configure_logging(
        service_name="market-data-dispatcher",
        level=getattr(settings, "log_level", "INFO"),
        json=getattr(settings, "log_json", True),
    )
    log = get_logger("market_data.dispatcher_main")  # type: ignore[no-any-return]
    log.info("market_data_dispatcher_starting")

    try:
        process = DispatcherProcess(settings=settings)

        # PLAN-0107 B-3: expose Prometheus /metrics so this dispatcher is scrape-able.
        metrics_handle = start_metrics_server(
            service_name="market-data-dispatcher",
            port=int(os.environ.get("METRICS_PORT", "9100")),
        )

        log_runtime_banner(
            "market-data-dispatcher",
            dependencies={
                "postgres_dsn": str(settings.database_url),
                "kafka_brokers": settings.kafka_bootstrap_servers,
            },
        )

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, process.stop)

        try:
            await process.run()
        finally:
            with contextlib.suppress(Exception):
                await metrics_handle.aclose()
    except Exception:
        log.exception("market_data_dispatcher_startup_failed")
        raise
    finally:
        log.info("market_data_dispatcher_stopped")


def main() -> None:
    """Synchronous entry-point for ``python -m market_data.infrastructure.messaging.outbox.dispatcher_main``."""
    asyncio.run(_run_dispatcher())


if __name__ == "__main__":
    main()
