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
from observability import start_metrics_server  # type: ignore[import-untyped]


async def _run_worker() -> None:
    """Async entry-point; installs signal handlers for graceful shutdown."""
    settings = Settings()  # type: ignore[call-arg]
    worker = WorkerProcess(settings=settings)

    # Phase 3 worker-metrics rollout — expose Prometheus /metrics so the
    # s2_mi_provider_* fetch counters/histograms can be scraped.
    metrics_handle = start_metrics_server(
        service_name="market-ingestion-worker",
        port=int(os.environ.get("METRICS_PORT", "9100")),
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.stop)

    try:
        await worker.run()
    finally:
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()


def main() -> None:
    """Synchronous entry-point for ``python -m market_ingestion.infrastructure.workers.worker_main``."""
    asyncio.run(_run_worker())


if __name__ == "__main__":
    main()
