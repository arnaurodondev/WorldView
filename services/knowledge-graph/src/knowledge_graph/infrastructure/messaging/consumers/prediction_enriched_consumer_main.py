"""Standalone PredictionEnrichedConsumer entry point for S7 (Knowledge Graph).

Runs as an independent process (R22). Consumes ``nlp.article.enriched.v1`` in its
own consumer group, filters to Polymarket synthetic documents
(``source_type='polymarket'``), and materialises one ``temporal_events`` row
(event_type='prediction') + one ``entity_event_exposures`` row per resolved
entity.

Consumer group: ``kg-prediction-enriched-group``

Run with::

    python -m knowledge_graph.infrastructure.messaging.consumers.prediction_enriched_consumer_main

PLAN-0056 Wave C2 (PRD-0033).
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
    from knowledge_graph.infrastructure.messaging.consumers.prediction_enriched_consumer import (
        PredictionEnrichedConsumer,
    )
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from messaging.kafka.consumer.supervisor import (  # type: ignore[import-untyped]
        ConsumerExited,
        run_consumer_supervised,
    )
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="knowledge-graph-prediction-enriched-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("knowledge_graph.prediction_enriched_consumer_main")  # type: ignore[no-any-return]
    log.info("prediction_enriched_consumer_starting", service="knowledge-graph")

    # Phase 3 worker-metrics rollout — expose Prometheus /metrics on a dedicated
    # port. F-005 / BP-704: bind a stall-aware liveness probe so /healthz on the
    # metrics port flips to 503 when the poll loop wedges or run() dies.
    liveness_probe = make_liveness_probe()
    metrics_handle = start_metrics_server(
        service_name="knowledge-graph-prediction-enriched-consumer",
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

    # PLAN-0056 Wave C3: wire the MarketPolarityClassifier when a DeepInfra key is
    # configured. Empty key → classifier=None → exposures keep NULL polarity (no
    # behaviour change). Every LLM call is cost-logged (non-zero) via the
    # session-scoped KG usage logger so we never reintroduce the S6/S8 $0 bug.
    polarity_classifier = None
    deepinfra_key = settings.deepinfra_api_key.get_secret_value()
    if deepinfra_key:
        from knowledge_graph.infrastructure.intelligence_db.usage_log_factory import (
            SessionScopedKgUsageLogger,
        )
        from knowledge_graph.infrastructure.llm.market_polarity_classifier import (
            MarketPolarityClassifier,
        )

        polarity_classifier = MarketPolarityClassifier(
            api_key=deepinfra_key,
            api_base_url=settings.polarity_classifier_base_url,
            model_id=settings.polarity_classifier_model_id,
            timeout_seconds=settings.polarity_classifier_timeout_seconds,
            usage_logger=SessionScopedKgUsageLogger(write_factory),
        )
        log.info(
            "prediction_enriched_consumer_polarity_classifier_enabled",
            model=settings.polarity_classifier_model_id,
        )

    # PLAN-0056 Wave D2: PredictionSignalEmitter turns first-sight (new_market) and
    # resolution docs into per-entity market.prediction.signal.v1 signals via the
    # outbox. Always wired (no external dependency) — the new_market gate lives in
    # config (KNOWLEDGE_GRAPH_PREDICTION_SIGNAL_EMIT_NEW_MARKET).
    from knowledge_graph.application.services.prediction_signal_emitter import (
        PredictionSignalEmitter,
    )

    signal_emitter = PredictionSignalEmitter(
        emit_new_market=settings.prediction_signal_emit_new_market,
        new_market_base=settings.prediction_signal_new_market_base,
        resolution_base=settings.prediction_signal_resolution_base,
        material_move_adverse_factor=settings.prediction_signal_material_move_adverse_factor,
    )

    config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id="kg-prediction-enriched-group",
        topics=[settings.kafka_topic_enriched],
        # PLAN-0113 FIX-2: opt-in Kafka static membership (KIP-345). Empty default
        # = dynamic membership (no behaviour change); a stable id skips rebalances.
        group_instance_id=settings.kafka_prediction_enriched_consumer_instance_id,
    )
    consumer = PredictionEnrichedConsumer(
        config=config,
        session_factory=write_factory,
        dedup_client=valkey,
        # PLAN-0056 Wave C3: None when no DeepInfra key → exposures keep NULL polarity.
        polarity_classifier=polarity_classifier,
        # PLAN-0056 Wave D2: new_market + resolution prediction signals.
        signal_emitter=signal_emitter,
    )
    # Bind the probe so /healthz reflects this consumer's poll-loop progress.
    liveness_probe.bind(consumer)

    # PLAN-0107 B-4: emit single <service>_ready event after deps are wired.
    log_runtime_banner(
        "knowledge-graph-prediction-enriched-consumer",
        dependencies={
            "postgres_dsn": str(settings.database_url),
            "kafka_brokers": settings.kafka_bootstrap_servers,
            "valkey_url": getattr(settings, "valkey_url", None),
            "topics_subscribed": [settings.kafka_topic_enriched],
        },
    )

    try:
        # BP-704 supervision: races run() against the stop event so a crashed
        # run() can no longer leave an un-awaited dead task while main() hangs on
        # stop_event.wait(). A terminal run() exit raises ConsumerExited → exit
        # non-zero so Docker restarts the container cleanly.
        await run_consumer_supervised(consumer, stop_event, liveness_probe=liveness_probe)
    except ConsumerExited as exc:
        log.error("prediction_enriched_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    except Exception as exc:
        log.error("prediction_enriched_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    finally:
        await valkey.close()
        await engine.dispose()

        # Stop the Prometheus metrics HTTP server cleanly.
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()
        log.info("prediction_enriched_consumer_stopped")


if __name__ == "__main__":
    asyncio.run(main())
