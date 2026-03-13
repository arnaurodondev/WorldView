"""Standalone dispatcher process entrypoint for market-ingestion.

Runs ``MarketIngestionOutboxDispatcher`` in a loop, forwarding outbox
records to Kafka.  Intended to run as a separate container/process.

Usage (standalone)::

    python -m market_ingestion.messaging.dispatcher_main
"""

from __future__ import annotations

import asyncio
import signal

from market_ingestion.config import Settings
from market_ingestion.infrastructure.db.session import _build_factories
from market_ingestion.infrastructure.messaging.dispatcher import (
    build_market_ingestion_dispatcher,
)
from observability.logging import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)


class DispatcherProcess:
    """Wraps ``MarketIngestionOutboxDispatcher`` with a lifecycle API.

    Args:
        settings: Service configuration.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        write_factory, _ = _build_factories(settings)
        self._dispatcher = build_market_ingestion_dispatcher(
            settings=settings,
            write_factory=write_factory,
        )

    def stop(self) -> None:
        """Signal the dispatcher loop to stop."""
        self._dispatcher.stop()

    async def run(self) -> None:
        """Run the dispatcher until ``stop()`` is called."""
        logger.info("dispatcher_starting")
        await self._dispatcher.run()
        logger.info("dispatcher_stopped")


async def _run_dispatcher() -> None:
    """Async entry-point; installs signal handlers for graceful shutdown."""
    settings = Settings()
    process = DispatcherProcess(settings=settings)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, process.stop)

    await process.run()


def main() -> None:
    """Synchronous entry-point for ``python -m market_ingestion.messaging.dispatcher_main``."""
    asyncio.run(_run_dispatcher())


if __name__ == "__main__":
    main()
