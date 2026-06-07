"""Market-ingestion worker standalone entry point.

Claims and executes ingestion tasks.  Intended to run as a separate
container/process.

Usage (standalone)::

    python -m market_ingestion.infrastructure.workers.worker_main
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal

from market_ingestion.config import Settings
from market_ingestion.infrastructure.workers.worker import WorkerProcess
from observability import (  # type: ignore[import-untyped]
    configure_logging,
    get_logger,
    log_runtime_banner,
    start_metrics_server,
)


async def _run_worker() -> None:
    """Async entry-point; installs signal handlers for graceful shutdown."""
    settings = Settings()  # type: ignore[call-arg]

    # PLAN-0107 B-4 — full logging lifecycle (worst-6 fix).
    configure_logging(
        service_name="market-ingestion-worker",
        level=getattr(settings, "log_level", "INFO"),
        json=getattr(settings, "log_json", True),
    )
    log = get_logger("market_ingestion.worker_main")  # type: ignore[no-any-return]
    log.info("market_ingestion_worker_starting")

    try:
        worker = WorkerProcess(settings=settings)

        # Phase 3 worker-metrics rollout — expose Prometheus /metrics so the
        # s2_mi_provider_* fetch counters/histograms can be scraped.
        metrics_handle = start_metrics_server(
            service_name="market-ingestion-worker",
            port=int(os.environ.get("METRICS_PORT", "9100")),
        )

        log_runtime_banner(
            "market-ingestion-worker",
            dependencies={
                "postgres_dsn": str(settings.database_url),
                "kafka_brokers": settings.kafka_bootstrap_servers,
                "valkey_url": getattr(settings, "valkey_url", None),
            },
        )

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, worker.stop)

        try:
            await worker.run()
        finally:
            with contextlib.suppress(Exception):
                await metrics_handle.aclose()
    except Exception:
        log.exception("market_ingestion_worker_startup_failed")
        raise
    finally:
        log.info("market_ingestion_worker_stopped")


def main() -> None:
    """Synchronous entry-point for ``python -m market_ingestion.infrastructure.workers.worker_main``."""
    asyncio.run(_run_worker())


if __name__ == "__main__":
    main()
