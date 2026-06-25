"""Standalone outbox dispatcher entry point for the Content Store service (S5).

Runs as an independent process (R22) with its own session factory and signal
handling.  Uses the write session factory only — the dispatcher reads and
updates outbox rows within the same transaction.

Run with::

    python -m content_store.infrastructure.messaging.outbox.dispatcher_main
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys

from observability import (  # type: ignore[import-untyped]
    configure_logging,
    get_logger,
    log_runtime_banner,
    start_metrics_server,
)

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def main() -> None:
    from content_store.config import Settings
    from content_store.infrastructure.db.session import _build_factories
    from content_store.infrastructure.messaging.outbox.dispatcher import (
        ContentStoreOutboxDispatcher,
    )

    settings = Settings()
    configure_logging(
        service_name="content-store-dispatcher",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("content_store.dispatcher_main")  # type: ignore[no-any-return]
    log.info("dispatcher_starting", service="content-store")

    # Phase 2 worker-metrics: expose Prometheus /metrics endpoint.
    metrics_handle = start_metrics_server(
        service_name="content-store-dispatcher",
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
    dispatcher = ContentStoreOutboxDispatcher(settings, write_factory)

    # PLAN-0107 B-4: emit single <service>_ready event after deps are wired.
    log_runtime_banner(
        "content-store-dispatcher",
        dependencies={
            "postgres_dsn": str(settings.database_url),
            "kafka_brokers": settings.kafka_bootstrap_servers,
        },
    )

    try:
        dispatch_task = asyncio.create_task(dispatcher.run())
        await stop_event.wait()
        dispatcher.stop()
        dispatch_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await dispatch_task
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
