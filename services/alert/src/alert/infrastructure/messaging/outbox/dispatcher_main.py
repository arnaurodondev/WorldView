"""Standalone outbox dispatcher entry point for the Alert service (S10).

Runs as an independent process (R22) with its own session factory and signal
handling.  Uses the write session factory only — the dispatcher reads and
updates outbox rows within the same transaction.

Run with::

    python -m alert.infrastructure.messaging.outbox.dispatcher_main
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys

from observability import configure_logging, get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def main() -> None:
    from alert.config import Settings
    from alert.infrastructure.db.session import _build_factories
    from alert.infrastructure.messaging.outbox.dispatcher import (
        AlertOutboxDispatcher,
    )

    settings = Settings()
    configure_logging(
        service_name="alert-dispatcher",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("alert.dispatcher_main")  # type: ignore[no-any-return]
    log.info("dispatcher_starting", service="alert")

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    # Use dual factory but only pass write_factory to dispatcher (R22, R23)
    _engine, write_factory, _read_factory = _build_factories(settings)
    dispatcher = AlertOutboxDispatcher(settings=settings, session_factory=write_factory)

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
    else:
        log.info("dispatcher_stopped")
    finally:
        await _engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
