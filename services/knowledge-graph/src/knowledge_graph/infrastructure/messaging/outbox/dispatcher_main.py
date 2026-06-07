"""Standalone outbox dispatcher entry point for the Knowledge Graph service (S7).

Runs as an independent process (R22) with supervised restart on crash.
Uses the write session factory only — the dispatcher reads and updates
outbox rows within the same transaction.

Run with::

    python -m knowledge_graph.infrastructure.messaging.outbox.dispatcher_main
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
    log_runtime_banner,
    start_metrics_server,
)

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def _supervised_run(
    dispatcher: object,
    stop_event: asyncio.Event,
) -> None:
    """Restart the outbox dispatcher on crash with exponential backoff."""
    failures = 0
    while not stop_event.is_set():
        try:
            await dispatcher.run_forever()  # type: ignore[attr-defined]
            break
        except asyncio.CancelledError:
            raise
        except Exception:
            failures += 1
            delay = min(5 * (2**failures), 300)
            logger.exception(  # type: ignore[no-any-return]
                "dispatcher_crashed",
                restart_delay=delay,
                failures=failures,
            )
            await asyncio.sleep(delay)


async def main() -> None:
    from confluent_kafka import Producer  # type: ignore[import-untyped]

    from knowledge_graph.config import Settings
    from knowledge_graph.infrastructure.intelligence_db.session import _build_factories
    from knowledge_graph.infrastructure.messaging.outbox.dispatcher import OutboxDispatcher

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="knowledge-graph-dispatcher",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("knowledge_graph.dispatcher_main")  # type: ignore[no-any-return]
    log.info("dispatcher_starting", service="knowledge-graph")

    # Phase 2 worker-metrics: expose Prometheus /metrics endpoint.
    metrics_handle = start_metrics_server(
        service_name="knowledge-graph-dispatcher",
        port=int(os.environ.get("METRICS_PORT", "9100")),
    )

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    # Write factory only — dispatcher reads/updates outbox rows in write txn
    engine, _read_engine, write_factory, _read_factory = _build_factories(settings)

    producer = Producer({"bootstrap.servers": settings.kafka_bootstrap_servers})
    dispatcher = OutboxDispatcher(
        session_factory=write_factory,
        producer=producer,  # type: ignore[arg-type]
        poll_interval_s=settings.dispatcher_poll_interval_s,
        batch_size=settings.dispatcher_batch_size,
    )

    # PLAN-0107 B-4: emit single <service>_ready event after deps are wired.
    log_runtime_banner(
        "knowledge-graph-dispatcher",
        dependencies={
            "postgres_dsn": str(settings.database_url),
            "kafka_brokers": settings.kafka_bootstrap_servers,
        },
    )

    try:
        dispatch_task = asyncio.create_task(_supervised_run(dispatcher, stop_event))
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
        await metrics_handle.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
