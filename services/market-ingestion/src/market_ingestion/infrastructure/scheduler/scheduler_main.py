"""Market-ingestion scheduler standalone entry point.

Starts ``SchedulerProcess`` and installs signal handlers for graceful shutdown
(SIGINT, SIGTERM).  Intended to run as a separate container/process.

Usage (standalone)::

    python -m market_ingestion.infrastructure.scheduler.scheduler_main
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal

from market_ingestion.config import Settings
from market_ingestion.infrastructure.scheduler.scheduler import SchedulerProcess
from observability import (  # type: ignore[import-untyped]
    configure_logging,
    get_logger,
    log_runtime_banner,
    start_metrics_server,
)


async def _run_scheduler() -> None:
    """Async entry-point; installs signal handlers for graceful shutdown."""
    settings = Settings()  # type: ignore[call-arg]

    # PLAN-0107 B-4 — full logging lifecycle (worst-6 fix).
    configure_logging(
        service_name="market-ingestion-scheduler",
        level=getattr(settings, "log_level", "INFO"),
        json=getattr(settings, "log_json", True),
    )
    log = get_logger("market_ingestion.scheduler_main")  # type: ignore[no-any-return]
    log.info("market_ingestion_scheduler_starting")

    try:
        scheduler = SchedulerProcess(settings=settings)

        # Phase 3 worker-metrics rollout — expose Prometheus /metrics.
        metrics_handle = start_metrics_server(
            service_name="market-ingestion-scheduler",
            port=int(os.environ.get("METRICS_PORT", "9100")),
        )

        log_runtime_banner(
            "market-ingestion-scheduler",
            dependencies={
                "postgres_dsn": str(settings.database_url),
                "kafka_brokers": settings.kafka_bootstrap_servers,
            },
        )

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, scheduler.stop)

        try:
            await scheduler.run()
        finally:
            with contextlib.suppress(Exception):
                await metrics_handle.aclose()
    except Exception:
        log.exception("market_ingestion_scheduler_startup_failed")
        raise
    finally:
        log.info("market_ingestion_scheduler_stopped")


def main() -> None:
    """Synchronous entry-point for ``python -m market_ingestion.infrastructure.scheduler.scheduler_main``."""
    asyncio.run(_run_scheduler())


if __name__ == "__main__":
    main()
