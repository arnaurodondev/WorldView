"""Content-ingestion worker standalone entry point.

Claims and executes content ingestion tasks.  Intended to run as a separate
container/process.

Usage (standalone)::

    python -m content_ingestion.infrastructure.workers.worker_main
"""

from __future__ import annotations

import asyncio
import signal

from content_ingestion.config import Settings
from content_ingestion.infrastructure.workers.worker import WorkerProcess


async def _run_worker() -> None:
    """Async entry-point; installs signal handlers for graceful shutdown."""
    settings = Settings()  # type: ignore[call-arg]
    worker = WorkerProcess(settings=settings)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.stop)

    await worker.run()


def main() -> None:
    """Synchronous entry-point for ``python -m content_ingestion.infrastructure.workers.worker_main``."""
    asyncio.run(_run_worker())


if __name__ == "__main__":
    main()
