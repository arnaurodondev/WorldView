"""Standalone scheduler entry point for the Knowledge Graph service (S7).

Runs as an independent process (R22). Starts the APScheduler-based
``KnowledgeGraphScheduler`` with all 8 worker jobs.  Worker slots that
require an LLM client are wired best-effort — jobs fall back to no-op
stubs when the client is unavailable.

Run with::

    python -m knowledge_graph.infrastructure.scheduler.scheduler_main
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys

from observability import configure_logging, get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def main() -> None:
    from knowledge_graph.config import Settings
    from knowledge_graph.infrastructure.intelligence_db.session import _build_factories
    from knowledge_graph.infrastructure.scheduler.scheduler import (
        KnowledgeGraphScheduler,
        build_workers,
    )

    settings = Settings()
    configure_logging(
        service_name="knowledge-graph-scheduler",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("knowledge_graph.scheduler_main")  # type: ignore[no-any-return]
    log.info("scheduler_starting", service="knowledge-graph")

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    engine, write_factory, _read_factory = _build_factories(settings)

    # LLM workers use stubs when no adapters are configured (matches original app.py behaviour)
    workers = build_workers(settings, write_factory, llm_client=None)
    scheduler = KnowledgeGraphScheduler(settings, workers=workers)

    # Standalone scheduler: no consumer coroutine — use an async no-op
    async def _noop_consumer() -> None:
        """No-op consumer placeholder — consumers run in separate processes."""
        await stop_event.wait()

    try:
        await scheduler.start(_noop_consumer())
        await stop_event.wait()
    except Exception as exc:
        log.error("scheduler_fatal_error", error=str(exc))
        sys.exit(1)
    else:
        log.info("scheduler_stopped")
    finally:
        with contextlib.suppress(Exception):
            await scheduler.stop()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
