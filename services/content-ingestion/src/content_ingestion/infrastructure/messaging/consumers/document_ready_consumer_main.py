"""Standalone document-ready consumer entry point for Content Ingestion (S4).

Runs as an independent process (R22).  Consumes ``nlp.document.ready.v1``
events emitted by S6 and calls ``set_ready()`` on the upload repository to
transition tenant uploads to ``status=ready``.

Run with::

    python -m content_ingestion.infrastructure.messaging.consumers.document_ready_consumer_main

PLAN-0086 Wave F-1 (T-F-1-02).
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
    make_liveness_probe,
    start_metrics_server,
)

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def main() -> None:
    from content_ingestion.config import Settings
    from content_ingestion.infrastructure.db.session import _build_factories
    from content_ingestion.infrastructure.messaging.consumers.document_ready_consumer import (
        DocumentReadyConsumer,
    )
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from messaging.kafka.consumer.supervisor import (  # type: ignore[import-untyped]
        ConsumerExited,
        run_consumer_supervised,
    )
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="content-ingestion-document-ready-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("content_ingestion.document_ready_consumer_main")  # type: ignore[no-any-return]
    log.info("document_ready_consumer_starting", service="content-ingestion")

    # F-005/BP-704: expose Prometheus /metrics + stall-aware /healthz so the
    # Docker healthcheck (GET http://localhost:9100/healthz) can actually
    # connect. The liveness probe flips /healthz to 503 when the poll loop
    # wedges or the run() task dies, so a wedged consumer no longer keeps a
    # GREEN healthcheck and gets restarted.
    liveness_probe = make_liveness_probe()
    metrics_handle = start_metrics_server(
        service_name="content-ingestion-document-ready-consumer",
        port=int(os.environ.get("METRICS_PORT", "9100")),
        liveness_probe=liveness_probe,
    )

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    # Content-ingestion write session factory (set_ready is a write UPDATE).
    ci_engine, _ci_read_engine, ci_sf, _ci_read_sf = _build_factories(settings)

    # Valkey client for ValkeyDedupMixin fast-path dedup.
    # None means at-least-once mode (safe because set_ready UPDATE is idempotent).
    valkey = create_valkey_client_from_url(settings.valkey_url)

    consumer_config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id="s4-document-ready",
        topics=["nlp.document.ready.v1"],
        # PLAN-0113 FIX-2: opt-in static membership id (empty = dynamic, no-op).
        group_instance_id=settings.kafka_document_ready_consumer_instance_id,
    )

    consumer = DocumentReadyConsumer(
        config=consumer_config,
        session_factory=ci_sf,
        valkey_client=valkey,
    )
    # Bind the probe so /healthz reflects this consumer's poll-loop progress.
    liveness_probe.bind(consumer)

    # PLAN-0107 B-4: emit single <service>_ready event after deps are wired.
    log_runtime_banner(
        "content-ingestion-document-ready-consumer",
        dependencies={
            "postgres_dsn": str(settings.db_url),
            "kafka_brokers": settings.kafka_bootstrap_servers,
            "valkey_url": getattr(settings, "valkey_url", None),
            "topics_subscribed": ["nlp.document.ready.v1"],
        },
    )

    try:
        # F-005/BP-704 FAILURE MODE 2 supervision: races run() against the stop
        # event so a crashed run() (e.g. GroupCoordinator connection-setup
        # timeout) can no longer leave a dead task while main() hangs on
        # ``stop_event.wait()``. A terminal run() exit raises ConsumerExited →
        # we exit non-zero so Docker restarts the container cleanly.
        await run_consumer_supervised(consumer, stop_event, liveness_probe=liveness_probe)
    except ConsumerExited as exc:
        log.error("document_ready_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    except Exception as exc:
        log.error("document_ready_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    finally:
        await valkey.close()
        await ci_engine.dispose()
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()
        log.info("document_ready_consumer_stopped")


if __name__ == "__main__":
    asyncio.run(main())
