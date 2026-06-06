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
from observability import start_metrics_server  # type: ignore[import-untyped]


async def _run_scheduler() -> None:
    """Async entry-point; installs signal handlers for graceful shutdown."""
    settings = Settings()  # type: ignore[call-arg]
    scheduler = SchedulerProcess(settings=settings)

    # Phase 3 worker-metrics rollout — expose Prometheus /metrics.
    metrics_handle = start_metrics_server(
        service_name="market-ingestion-scheduler",
        port=int(os.environ.get("METRICS_PORT", "9100")),
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, scheduler.stop)

    try:
        await scheduler.run()
    finally:
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()


def main() -> None:
    """Synchronous entry-point for ``python -m market_ingestion.infrastructure.scheduler.scheduler_main``."""
    asyncio.run(_run_scheduler())


if __name__ == "__main__":
    main()
