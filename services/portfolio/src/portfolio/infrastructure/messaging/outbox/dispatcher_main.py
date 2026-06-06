"""Standalone outbox dispatcher entry point.

Run with: python -m portfolio.infrastructure.messaging.outbox.dispatcher_main
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys

from observability import (  # type: ignore[import-untyped]
    configure_logging,
    get_logger,
    start_metrics_server,
)

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def main() -> None:
    from portfolio.config import Settings
    from portfolio.infrastructure.db.session import _build_factories
    from portfolio.infrastructure.messaging.outbox.dispatcher import create_dispatcher

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("portfolio.dispatcher_main")  # type: ignore[no-any-return]
    log.info("dispatcher_starting", service=settings.service_name)

    # Phase 2 worker-metrics: expose Prometheus /metrics endpoint so the
    # dispatcher's outbox lag/throughput counters are scrapable.
    metrics_handle = start_metrics_server(
        service_name="portfolio-dispatcher",
        port=int(os.environ.get("METRICS_PORT", "9100")),
    )

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    _engine, _read_engine, write_factory, _read_factory = _build_factories(settings)

    dispatcher = create_dispatcher(settings, write_factory)

    try:
        dispatch_task = asyncio.create_task(dispatcher.run())
        await stop_event.wait()
        dispatcher.stop()
        dispatch_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await dispatch_task
    except Exception as exc:
        log.error("dispatcher_fatal_error", error=str(exc))
        sys.exit(1)
    finally:
        await metrics_handle.aclose()
        await _engine.dispose()
        log.info("dispatcher_stopped")


if __name__ == "__main__":
    asyncio.run(main())
