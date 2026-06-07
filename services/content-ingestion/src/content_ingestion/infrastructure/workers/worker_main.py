"""Content-ingestion worker standalone entry point.

Claims and executes content ingestion tasks.  Intended to run as a separate
container/process.

Usage (standalone)::

    python -m content_ingestion.infrastructure.workers.worker_main
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal

from content_ingestion.config import Settings
from content_ingestion.infrastructure.workers.worker import WorkerProcess
from observability import (  # type: ignore[import-untyped]
    configure_logging,
    get_logger,
    log_runtime_banner,
    start_metrics_server,
)


async def _run_worker() -> None:
    """Async entry-point; installs signal handlers for graceful shutdown."""
    settings = Settings()  # type: ignore[call-arg]

    # Wire structured logging before the metrics server so its
    # ``metrics_server_started`` event lands in the same JSON format as
    # the rest of the worker's logs.
    configure_logging(
        service_name="content-ingestion-worker",
        level=getattr(settings, "log_level", "INFO"),
        json=getattr(settings, "log_json", True),
    )
    log = get_logger("content_ingestion.worker_main")  # type: ignore[no-any-return]
    log.info("content_ingestion_worker_starting")

    try:
        # Stand up the worker's /metrics + /healthz endpoint so Prometheus
        # can scrape this background process the same way it scrapes the
        # API services.  METRICS_PORT defaults to 9100 (see PRD-0028 worker
        # metrics rollout, phase 1 pilot).
        metrics_handle = start_metrics_server(
            service_name="content-ingestion-worker",
            port=int(os.environ.get("METRICS_PORT", "9100")),
        )

        worker = WorkerProcess(settings=settings)

        log_runtime_banner(
            "content-ingestion-worker",
            dependencies={
                "postgres_dsn": str(settings.db_url),
                "kafka_brokers": getattr(settings, "kafka_bootstrap_servers", None),
                "valkey_url": getattr(settings, "valkey_url", None),
            },
        )

        loop = asyncio.get_running_loop()

        # Background tasks scheduled from the signal handler — kept on a
        # module-style list so ruff RUF006 is satisfied and the GC does not
        # eagerly drop the still-running coroutine.
        _bg_tasks: list[asyncio.Task[None]] = []

        def _shutdown() -> None:
            # The original handler only stopped the worker.  We now ALSO
            # need to stop the metrics ASGI server — schedule its async
            # close as a task because signal handlers must be sync.
            worker.stop()
            _bg_tasks.append(loop.create_task(metrics_handle.aclose()))

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _shutdown)

        try:
            await worker.run()
        finally:
            # Defence-in-depth: if the worker exits without a signal (e.g.
            # because run() returned cleanly), the metrics server still
            # needs to stop or asyncio.run() will hang waiting for the
            # uvicorn task.  aclose() is idempotent.
            with contextlib.suppress(Exception):
                await metrics_handle.aclose()
    except Exception:
        log.exception("content_ingestion_worker_startup_failed")
        raise
    finally:
        log.info("content_ingestion_worker_stopped")


def main() -> None:
    """Synchronous entry-point for ``python -m content_ingestion.infrastructure.workers.worker_main``."""
    asyncio.run(_run_worker())


if __name__ == "__main__":
    main()
