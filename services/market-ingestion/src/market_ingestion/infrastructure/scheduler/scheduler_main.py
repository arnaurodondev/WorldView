"""Market-ingestion scheduler standalone entry point.

Starts ``SchedulerProcess`` and installs signal handlers for graceful shutdown
(SIGINT, SIGTERM).  Intended to run as a separate container/process.

Usage (standalone)::

    python -m market_ingestion.infrastructure.scheduler.scheduler_main
"""

from __future__ import annotations

import asyncio
import signal

from market_ingestion.config import Settings
from market_ingestion.infrastructure.scheduler.scheduler import SchedulerProcess


async def _run_scheduler() -> None:
    """Async entry-point; installs signal handlers for graceful shutdown."""
    settings = Settings()  # type: ignore[call-arg]
    scheduler = SchedulerProcess(settings=settings)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, scheduler.stop)

    await scheduler.run()


def main() -> None:
    """Synchronous entry-point for ``python -m market_ingestion.infrastructure.scheduler.scheduler_main``."""
    asyncio.run(_run_scheduler())


if __name__ == "__main__":
    main()
