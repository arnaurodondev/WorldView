"""Standalone outbox dispatcher entry point for the Content-Ingestion service.

Runs as an independent process (R22) with its own session factory and signal
handling.  Uses the write session factory only — the dispatcher reads and
updates outbox rows within the same transaction.

Besides forwarding outbox records to Kafka, this process also hosts the
**retention pruners** for the two unbounded content_ingestion_db tables that
caused the 2026-07-18 disk-full outage (see
``libs/messaging/kafka/maintenance/table_retention.py``):

* ``outbox_events`` — delivered rows are pruned after a short window.
* ``prediction_market_fetch_log`` — dedup rows are pruned after a longer window.

The dispatcher is the natural host: it is already a long-lived, single-replica
process with a write session factory to the same DB, so no new deployment is
required to start reclaiming space.

Run with::

    python -m content_ingestion.infrastructure.messaging.outbox.dispatcher_main
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys
from datetime import timedelta
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from content_ingestion.config import Settings

logger = get_logger(__name__)  # type: ignore[no-any-return]


def _build_retention_workers(settings: Settings) -> list[RetentionCleanupWorker]:
    """Build the enabled content_ingestion_db retention pruners.

    A retention window of 0 disables that table's pruner (returns no worker),
    so pruning can be turned off per-table via env without a redeploy.
    """
    workers: list[RetentionCleanupWorker] = []

    # ── outbox_events: prune delivered rows only (primary fix) ──────────────
    if settings.outbox_retention_seconds > 0:
        workers.append(
            RetentionCleanupWorker(
                policy=RetentionPolicy(
                    table="outbox_events",
                    pk_column="id",
                    # ``dispatched_at`` is set together with status='delivered' by
                    # OutboxRepository.mark_published — guaranteed non-null for
                    # delivered rows (verified live 2026-07-18: 0 null / 50663 set).
                    age_column="dispatched_at",
                    retention=timedelta(seconds=settings.outbox_retention_seconds),
                    # CRITICAL: only ever delete delivered rows. Pending/processing/
                    # failed/dead_letter rows are still owed to Kafka or triage.
                    status_column="status",
                    status_value="delivered",
                ),
                service_name="content-ingestion",
                batch_size=settings.outbox_prune_batch_size,
                max_batches=settings.outbox_prune_max_batches,
            )
        )

    # ── prediction_market_fetch_log: prune old dedup rows ───────────────────
    if settings.prediction_fetch_log_retention_days > 0:
        workers.append(
            RetentionCleanupWorker(
                policy=RetentionPolicy(
                    table="prediction_market_fetch_log",
                    pk_column="id",
                    # ``created_at`` (server_default now()) is the monotonic append
                    # time — always non-null, unlike snapshot_at/fetched_at which
                    # are provider-supplied.
                    age_column="created_at",
                    retention=timedelta(days=settings.prediction_fetch_log_retention_days),
                ),
                service_name="content-ingestion",
                batch_size=settings.prediction_fetch_log_prune_batch_size,
                max_batches=settings.prediction_fetch_log_prune_max_batches,
            )
        )

    return workers


async def main() -> None:
    from content_ingestion.config import Settings
    from content_ingestion.infrastructure.db.session import _build_factories
    from content_ingestion.infrastructure.messaging.outbox.dispatcher import (
        ContentIngestionOutboxDispatcher,
    )

    settings = Settings()
    configure_logging(
        service_name="content-ingestion-dispatcher",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("content_ingestion.dispatcher_main")  # type: ignore[no-any-return]
    log.info("dispatcher_starting", service="content-ingestion")

    # Phase 2 worker-metrics: expose Prometheus /metrics endpoint.
    metrics_handle = start_metrics_server(
        service_name="content-ingestion-dispatcher",
        port=int(os.environ.get("METRICS_PORT", "9100")),
    )

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    # Use dual factory but only pass write_factory to dispatcher (R22, R23)
    _engine, _read_engine, write_factory, _read_factory = _build_factories(settings)
    dispatcher = ContentIngestionOutboxDispatcher(settings, write_factory)

    # Retention pruners share the dispatcher's write session factory (same DB).
    retention_workers = _build_retention_workers(settings)
    retention_coros = build_retention_loop_coros(
        workers=retention_workers,
        session_factory=write_factory,
        interval_seconds=settings.outbox_prune_interval_seconds,
        stop_event=stop_event,
    )
    for worker in retention_workers:
        log.info(
            "retention_pruner_enabled",
            table=worker.policy.table,
            status_filter=worker.policy.status_value,
            retention_seconds=int(worker.policy.retention.total_seconds()),
        )

    # PLAN-0107 B-4: emit single <service>_ready event after deps are wired.
    log_runtime_banner(
        "content-ingestion-dispatcher",
        dependencies={
            "postgres_dsn": str(settings.db_url),
            "kafka_brokers": settings.kafka_bootstrap_servers,
        },
    )

    background_tasks: list[asyncio.Task[None]] = []
    try:
        background_tasks.append(asyncio.create_task(dispatcher.run()))
        for coro in retention_coros:
            background_tasks.append(asyncio.create_task(coro()))
        await stop_event.wait()
        dispatcher.stop()
        for task in background_tasks:
            task.cancel()
        for task in background_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
    except Exception as exc:
        log.error("dispatcher_fatal_error", error=str(exc))
        sys.exit(1)
    else:
        log.info("dispatcher_stopped")
    finally:
        await metrics_handle.aclose()
        await _engine.dispose()
        if _read_engine is not _engine:
            await _read_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
