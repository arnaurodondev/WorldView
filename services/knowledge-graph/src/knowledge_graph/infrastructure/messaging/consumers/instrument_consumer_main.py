"""Standalone instrument entity consumer entry point for the Knowledge Graph (S7).

Runs as an independent process (R22). Consumes ``market.instrument.created``
events and creates canonical entities with aliases and embeddings.

Requires an LLM client (FallbackChainClient) for alias generation and
definition embedding.  Exits if LLM client cannot be initialized.

Run with::

    python -m knowledge_graph.infrastructure.messaging.consumers.instrument_consumer_main
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
    from knowledge_graph.infrastructure.messaging.consumers.instrument_consumer import (
        InstrumentEntityConsumer,
    )
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from messaging.kafka.consumer.supervisor import (  # type: ignore[import-untyped]
        ConsumerExited,
        run_consumer_supervised,
    )
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="knowledge-graph-instrument-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("knowledge_graph.instrument_consumer_main")  # type: ignore[no-any-return]
    log.info("instrument_consumer_starting", service="knowledge-graph")

    # Phase 3 worker-metrics rollout — expose Prometheus /metrics on a
    # dedicated port so the worker's counters/gauges become scrape-able.
    # F-005 / BP-704: bind a stall-aware liveness probe so /healthz on the
    # metrics port flips to 503 when the poll loop wedges or run() dies.
    liveness_probe = make_liveness_probe()
    metrics_handle = start_metrics_server(
        service_name="knowledge-graph-instrument-consumer",
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

    engine, _read_engine, write_factory, read_factory = _build_factories(settings)
    # Read-replica factory for the narrative use case's READ session (R27).  Falls
    # back to the write factory when no replica is configured.
    _read_factory = read_factory if read_factory is not None else write_factory
    valkey = create_valkey_client_from_url(settings.valkey_url)

    # FallbackChainClient with no adapters — ML calls return None (graceful no-op)
    from knowledge_graph.infrastructure.intelligence_db.usage_log_factory import (
        SessionScopedKgUsageLogger,
    )
    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient
    from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker

    # PLAN-0057 A-5 / F-CRIT-03: thread the session-scoped KG usage logger
    # into FallbackChainClient so every embed/extract attempt (success OR
    # failure) writes one row to intelligence_db.llm_usage_log.  Without
    # this, the KG cost-log table stayed permanently empty.
    kg_usage_logger = SessionScopedKgUsageLogger(write_factory)

    llm_client = FallbackChainClient(usage_logger=kg_usage_logger)
    definition_worker = DefinitionRefreshWorker(
        write_factory,
        llm_client,
        embedding_model_id=settings.embedding_model_id,
    )

    # 2026-06-14 P2: build the narrative use case so newly-minted instruments get
    # their `narrative` source_text at create-time instead of waiting up to a full
    # Worker 13D-3 cycle.  Construction mirrors the scheduler factory
    # (infrastructure/scheduler/scheduler.py): a dedicated DeepInfra chat client
    # bypasses the JSON-mode extraction path (which forces template-v1 for ~97% of
    # entities), and concrete repo classes are injected to honour R12 (no infra
    # imports inside the application-layer use case).  Wrapped defensively so a
    # missing API key or import error never blocks the consumer from starting —
    # it simply falls back to the periodic worker.
    narrative_use_case = None
    try:
        from knowledge_graph.application.use_cases.generate_narrative import GenerateNarrativeUseCase
        from knowledge_graph.infrastructure.intelligence_db.repositories.narrative_repository import (
            NarrativeRepository,
        )
        from knowledge_graph.infrastructure.intelligence_db.repositories.outbox import OutboxRepository

        narrative_model_id = getattr(
            settings,
            "narrative_llm_model_id",
            "meta-llama/Meta-Llama-3.1-8B-Instruct",
        )
        narrative_chat_client = None
        try:
            api_key = settings.deepinfra_api_key.get_secret_value()
        except Exception:
            api_key = ""
        if api_key:
            from knowledge_graph.infrastructure.llm.narrative_chat import DeepInfraNarrativeChatClient

            narrative_chat_client = DeepInfraNarrativeChatClient(
                api_key=api_key,
                model_id=narrative_model_id,
                base_url=getattr(
                    settings,
                    "deepinfra_extraction_base_url",
                    "https://api.deepinfra.com/v1/openai",
                ),
            )

        narrative_use_case = GenerateNarrativeUseCase(
            write_session_factory=write_factory,
            read_session_factory=_read_factory,
            narrative_llm_model_id=narrative_model_id,
            llm_client=llm_client,  # may degrade to template-v1 if chat client absent
            narrative_repo_class=NarrativeRepository,
            outbox_repo_class=OutboxRepository,
            narrative_chat_client=narrative_chat_client,
        )
        log.info("instrument_consumer_narrative_trigger_enabled", chat_client=bool(narrative_chat_client))
    except Exception as exc:
        log.warning("instrument_consumer_narrative_trigger_disabled", error=str(exc))
        narrative_use_case = None

    config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=f"{settings.kafka_consumer_group}-instrument",
        topics=[settings.kafka_topic_instrument_created],
        # PLAN-0113 FIX-2: opt-in Kafka static membership (KIP-345). Empty default
        # = dynamic membership (no behaviour change); a stable id skips rebalances.
        group_instance_id=settings.kafka_instrument_consumer_instance_id,
    )
    consumer = InstrumentEntityConsumer(
        config=config,
        session_factory=write_factory,
        llm_client=llm_client,
        definition_worker=definition_worker,
        narrative_use_case=narrative_use_case,
        dedup_client=valkey,
    )
    # Bind the probe so /healthz reflects this consumer's poll-loop progress.
    liveness_probe.bind(consumer)

    # PLAN-0107 B-4: emit single <service>_ready event after deps are wired.
    log_runtime_banner(
        "knowledge-graph-instrument-consumer",
        dependencies={
            "postgres_dsn": str(settings.database_url),
            "kafka_brokers": settings.kafka_bootstrap_servers,
            "valkey_url": getattr(settings, "valkey_url", None),
            "topics_subscribed": [settings.kafka_topic_instrument_created],
        },
    )

    try:
        # BP-704 supervision: races run() against the stop event so a crashed
        # run() can no longer leave an un-awaited dead task while main() hangs
        # on stop_event.wait(). A terminal run() exit raises ConsumerExited →
        # exit non-zero so Docker restarts the container cleanly.
        await run_consumer_supervised(consumer, stop_event, liveness_probe=liveness_probe)
    except ConsumerExited as exc:
        log.error("instrument_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    except Exception as exc:
        log.error("instrument_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    finally:
        await valkey.close()
        await engine.dispose()

        # Stop the Prometheus metrics HTTP server cleanly.
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()
        log.info("instrument_consumer_stopped")


if __name__ == "__main__":
    asyncio.run(main())
