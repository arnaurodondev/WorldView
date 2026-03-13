"""Standalone dispatcher process entrypoint for market-data.

Runs ``MarketDataOutboxDispatcher`` in a loop, forwarding outbox
records to Kafka.  Intended to run as a separate container/process.

Usage (standalone)::

    python -m market_data.infrastructure.messaging.outbox.dispatcher_main
"""

from __future__ import annotations

import asyncio
import signal

from market_data.config import Settings
from market_data.infrastructure.db.session import build_session_factory, build_write_engine
from market_data.infrastructure.messaging.outbox.dispatcher import create_dispatcher
from observability.logging import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)


class DispatcherProcess:
    """Wraps ``MarketDataOutboxDispatcher`` with a lifecycle API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        engine = build_write_engine(settings)
        write_factory = build_session_factory(engine)
        self._dispatcher = create_dispatcher(
            settings=settings,
            session_factory=write_factory,
        )

    def stop(self) -> None:
        """Signal the dispatcher loop to stop."""
        self._dispatcher.stop()

    async def run(self) -> None:
        """Run the dispatcher until ``stop()`` is called."""
        logger.info("dispatcher_starting", service="market-data")
        await self._dispatcher.run()
        logger.info("dispatcher_stopped", service="market-data")


async def _run_dispatcher() -> None:
    """Async entry-point; installs signal handlers for graceful shutdown."""
    settings = Settings()
    process = DispatcherProcess(settings=settings)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, process.stop)

    await process.run()


def main() -> None:
    """Synchronous entry-point for ``python -m market_data.infrastructure.messaging.outbox.dispatcher_main``."""
    asyncio.run(_run_dispatcher())


if __name__ == "__main__":
    main()
