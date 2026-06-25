"""Standalone outbox dispatcher entry point for the NLP Pipeline service (S6).

Runs as an independent process (R22) with supervised restart on crash.
The NLP dispatcher does NOT extend BaseOutboxDispatcher (it uses pre-serialized
bytes), so it has its own poll + produce loop.

Run with::

    python -m nlp_pipeline.infrastructure.messaging.outbox.dispatcher_main
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
            await dispatcher.run()  # type: ignore[attr-defined]
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
    from nlp_pipeline.config import Settings
    from nlp_pipeline.infrastructure.messaging.outbox.dispatcher import (
        NLPPipelineOutboxDispatcher,
    )
    from nlp_pipeline.infrastructure.nlp_db.session import _build_nlp_factories

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="nlp-pipeline-dispatcher",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("nlp_pipeline.dispatcher_main")  # type: ignore[no-any-return]
    log.info("dispatcher_starting", service="nlp-pipeline")

    # Phase 2 worker-metrics: expose Prometheus /metrics endpoint.
    metrics_handle = start_metrics_server(
        service_name="nlp-pipeline-dispatcher",
        port=int(os.environ.get("METRICS_PORT", "9100")),
    )

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    # Only nlp_db write factory needed for outbox dispatch
    nlp_engine, _nlp_read_engine, nlp_sf, _nlp_read_sf = _build_nlp_factories(settings)
    dispatcher = NLPPipelineOutboxDispatcher(settings=settings, session_factory=nlp_sf)

    # PLAN-0107 B-4: emit single <service>_ready event after deps are wired.
    log_runtime_banner(
        "nlp-pipeline-dispatcher",
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
        await nlp_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
