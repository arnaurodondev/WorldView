"""Standalone document-deletion consumer entry point for the NLP Pipeline (S6).

Runs as an independent process (R22).  Consumes ``content.document.deleted.v1``
and purges NLP artifacts (entity_mentions, sections, chunks) for deleted tenant
documents.

Run with::

    python -m nlp_pipeline.infrastructure.messaging.consumers.document_deletion_consumer_main

PLAN-0086 Wave F-1 (T-F-1-01).
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
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]
    from nlp_pipeline.config import Settings
    from nlp_pipeline.infrastructure.messaging.consumers.document_deletion_consumer import (
        DocumentDeletionConsumer,
    )
    from nlp_pipeline.infrastructure.nlp_db.session import _build_nlp_factories

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="nlp-pipeline-document-deletion-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("nlp_pipeline.document_deletion_consumer_main")  # type: ignore[no-any-return]
    log.info("document_deletion_consumer_starting", service="nlp-pipeline")

    # Phase 3 worker-metrics rollout — expose Prometheus /metrics on a
    # dedicated port so the worker's counters/gauges become scrape-able.
    metrics_handle = start_metrics_server(
        service_name="nlp-pipeline-document-deletion-consumer",
        port=int(os.environ.get("METRICS_PORT", "9100")),
    )

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    # NLP database session factory (write replica — deletions need the primary).
    nlp_engine, _nlp_read_engine, nlp_sf, _nlp_read_sf = _build_nlp_factories(settings)

    # Valkey client for ValkeyDedupMixin fast-path dedup.
    # None means at-least-once mode (safe because DELETE is idempotent).
    valkey = create_valkey_client_from_url(settings.valkey_url)

    consumer_config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id="s6-document-deletion",
        topics=["content.document.deleted.v1"],
    )

    consumer = DocumentDeletionConsumer(
        config=consumer_config,
        nlp_session_factory=nlp_sf,
        valkey_client=valkey,
    )

    try:
        consumer_task = asyncio.create_task(consumer.run())

        def _on_consumer_done(task: asyncio.Task) -> None:  # type: ignore[type-arg]
            if task.cancelled():
                return
            exc = task.exception()
            if exc is not None:
                log.error("document_deletion_consumer_task_crashed", error=str(exc), exc_info=exc)
                stop_event.set()

        consumer_task.add_done_callback(_on_consumer_done)

        await stop_event.wait()
        consumer.stop()  # type: ignore[attr-defined]
        try:
            await asyncio.wait_for(consumer_task, timeout=30.0)
        except TimeoutError:
            consumer_task.cancel()
            try:
                await asyncio.wait_for(consumer_task, timeout=5.0)
            except (asyncio.CancelledError, TimeoutError):
                log.warning("consumer_task_stuck_forcing_exit")
                sys.exit(1)
    except Exception as exc:
        log.error("document_deletion_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    else:
        log.info("document_deletion_consumer_stopped")
    finally:
        await valkey.close()
        await nlp_engine.dispose()

        # Stop the Prometheus metrics HTTP server cleanly.
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()


if __name__ == "__main__":
    asyncio.run(main())
