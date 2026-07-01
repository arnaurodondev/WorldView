"""Standalone fundamentals description consumer entry point for S7 (Knowledge Graph).

Runs as an independent process (R22). Consumes ``market.dataset.fetched``
events where ``dataset_type='fundamentals'``, detects description changes
via SHA-256 comparison, and triggers definition re-embedding when changed.

Run with::

    python -m knowledge_graph.infrastructure.messaging.consumers.fundamentals_consumer_main
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
    from knowledge_graph.config import Settings
    from knowledge_graph.infrastructure.intelligence_db.session import _build_factories
    from knowledge_graph.infrastructure.messaging.consumers.fundamentals_consumer import (
        FundamentalsDescriptionConsumer,
    )
    from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from messaging.kafka.consumer.supervisor import (  # type: ignore[import-untyped]
        ConsumerExited,
        run_consumer_supervised,
    )
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="knowledge-graph-fundamentals-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("knowledge_graph.fundamentals_consumer_main")  # type: ignore[no-any-return]
    log.info("fundamentals_consumer_starting", service="knowledge-graph")

    # Phase 3 worker-metrics rollout — expose Prometheus /metrics on a
    # dedicated port so the worker's counters/gauges become scrape-able.
    # F-005 / BP-704: bind a stall-aware liveness probe so /healthz on the
    # metrics port flips to 503 when the poll loop wedges or run() dies.
    liveness_probe = make_liveness_probe()
    metrics_handle = start_metrics_server(
        service_name="knowledge-graph-fundamentals-consumer",
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

    engine, _read_engine, write_factory, _read_factory = _build_factories(settings)
    valkey = create_valkey_client_from_url(settings.valkey_url)

    # Storage client — best-effort (needed for claim-check downloads)
    storage_client = None
    try:
        from storage.factory import build_object_storage  # type: ignore[import-untyped]
        from storage.settings import StorageSettings  # type: ignore[import-untyped]

        storage_settings = StorageSettings(
            endpoint=settings.storage_endpoint,
            access_key=settings.storage_access_key,
            secret_key=settings.storage_secret_key,
        )
        storage_client = build_object_storage(settings=storage_settings)
    except Exception:
        log.warning("storage_not_configured_fundamentals_downloads_disabled", exc_info=True)

    # Definition worker — FallbackChainClient with no adapters acts as no-op for ML calls
    from knowledge_graph.infrastructure.intelligence_db.usage_log_factory import (
        SessionScopedKgUsageLogger,
    )
    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

    # PLAN-0057 A-5 / F-CRIT-03: thread the usage logger so each embed/extract
    # attempt records a row in intelligence_db.llm_usage_log.
    kg_usage_logger = SessionScopedKgUsageLogger(write_factory)

    llm_client = FallbackChainClient(usage_logger=kg_usage_logger)
    # News-grounding (description audit 2026-06-17): wire an EntityEnrichmentAdapter
    # so consumer-triggered definition refreshes ground the LLM in the entity's own
    # recent news evidence. ``_read_factory`` may be None (no replica configured) —
    # the adapter then falls back to the write factory for its read session (R27).
    from knowledge_graph.infrastructure.intelligence_db.adapters.entity_enrichment_adapter import (
        EntityEnrichmentAdapter,
    )

    _def_evidence_provider = EntityEnrichmentAdapter(
        write_factory,
        read_session_factory=_read_factory,
    )
    definition_worker = DefinitionRefreshWorker(
        write_factory,
        llm_client,
        embedding_model_id=settings.embedding_model_id,
        evidence_provider=_def_evidence_provider,
    )

    config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=f"{settings.kafka_consumer_group}-fundamentals",
        topics=[settings.kafka_topic_dataset_fetched],
        # PLAN-0113 FIX-2: opt-in Kafka static membership (KIP-345). Empty default
        # = dynamic membership (no behaviour change); a stable id skips rebalances.
        group_instance_id=settings.kafka_fundamentals_consumer_instance_id,
    )
    consumer = FundamentalsDescriptionConsumer(
        config=config,
        session_factory=write_factory,
        definition_worker=definition_worker,
        storage_client=storage_client,
        dedup_client=valkey,
    )
    # Bind the probe so /healthz reflects this consumer's poll-loop progress.
    liveness_probe.bind(consumer)

    # PLAN-0107 B-4: emit single <service>_ready event after deps are wired.
    log_runtime_banner(
        "knowledge-graph-fundamentals-consumer",
        dependencies={
            "postgres_dsn": str(settings.database_url),
            "kafka_brokers": settings.kafka_bootstrap_servers,
            "valkey_url": getattr(settings, "valkey_url", None),
            "topics_subscribed": [settings.kafka_topic_dataset_fetched],
        },
    )

    try:
        # BP-704 supervision: races run() against the stop event so a crashed
        # run() can no longer leave an un-awaited dead task while main() hangs
        # on stop_event.wait(). A terminal run() exit raises ConsumerExited →
        # exit non-zero so Docker restarts the container cleanly.
        await run_consumer_supervised(consumer, stop_event, liveness_probe=liveness_probe)
    except ConsumerExited as exc:
        log.error("fundamentals_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    except Exception as exc:
        log.error("fundamentals_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    finally:
        await valkey.close()
        await engine.dispose()

        # Stop the Prometheus metrics HTTP server cleanly.
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()
        log.info("fundamentals_consumer_stopped")


if __name__ == "__main__":
    asyncio.run(main())
