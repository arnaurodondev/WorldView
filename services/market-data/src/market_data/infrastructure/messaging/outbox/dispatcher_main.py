"""Standalone dispatcher process entrypoint for market-data.

Runs ``MarketDataOutboxDispatcher`` in a loop, forwarding outbox
records to Kafka.  Intended to run as a separate container/process.

Usage (standalone)::

    python -m market_data.infrastructure.messaging.outbox.dispatcher_main
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal

from market_data.config import Settings
from market_data.infrastructure.db.session import build_session_factory, build_write_engine
from market_data.infrastructure.messaging.outbox.dispatcher import create_dispatcher
from observability import (  # type: ignore[import-untyped]
    configure_logging,
    get_logger,
    log_runtime_banner,
    start_metrics_server,
)

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
        await self._dispatcher.run()


async def _run_dispatcher() -> None:
    """Async entry-point; installs signal handlers for graceful shutdown."""
    settings = Settings()  # type: ignore[call-arg]

    # PLAN-0107 B-4 — full logging lifecycle (worst-6 fix).
    configure_logging(
        service_name="market-data-dispatcher",
        level=getattr(settings, "log_level", "INFO"),
        json=getattr(settings, "log_json", True),
    )
    log = get_logger("market_data.dispatcher_main")  # type: ignore[no-any-return]
    log.info("market_data_dispatcher_starting")

    try:
        process = DispatcherProcess(settings=settings)

        # PLAN-0107 B-3: expose Prometheus /metrics so this dispatcher is scrape-able.
        metrics_handle = start_metrics_server(
            service_name="market-data-dispatcher",
            port=int(os.environ.get("METRICS_PORT", "9100")),
        )

        log_runtime_banner(
            "market-data-dispatcher",
            dependencies={
                "postgres_dsn": str(settings.database_url),
                "kafka_brokers": settings.kafka_bootstrap_servers,
            },
        )

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, process.stop)

        try:
            await process.run()
        finally:
            with contextlib.suppress(Exception):
                await metrics_handle.aclose()
    except Exception:
        log.exception("market_data_dispatcher_startup_failed")
        raise
    finally:
        log.info("market_data_dispatcher_stopped")


def main() -> None:
    """Synchronous entry-point for ``python -m market_data.infrastructure.messaging.outbox.dispatcher_main``."""
    asyncio.run(_run_dispatcher())


if __name__ == "__main__":
    main()
