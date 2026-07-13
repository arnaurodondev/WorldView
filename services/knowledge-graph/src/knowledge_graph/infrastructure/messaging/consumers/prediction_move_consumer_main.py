"""Standalone PredictionMoveConsumer entry point for S7 (Knowledge Graph).

Runs as an independent process (R22). Consumes ``market.prediction.move.v1`` in
its own consumer group, joins each material move to the market's entity exposures
(``temporal_events.region == condition_id``), and emits one
``market.prediction.signal.v1`` per linked entity (``trigger='material_move'``)
via the outbox.

Consumer group: ``kg-prediction-move-group``

Run with::

    python -m knowledge_graph.infrastructure.messaging.consumers.prediction_move_consumer_main

PLAN-0056 Wave D2 (PRD-0033).
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
    from knowledge_graph.application.services.prediction_signal_emitter import (
        PredictionSignalEmitter,
    )
    from knowledge_graph.config import Settings
    from knowledge_graph.infrastructure.intelligence_db.session import _build_factories
    from knowledge_graph.infrastructure.messaging.consumers.prediction_move_consumer import (
        PredictionMoveConsumer,
    )
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from messaging.kafka.consumer.supervisor import (  # type: ignore[import-untyped]
        ConsumerExited,
        run_consumer_supervised,
    )
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="knowledge-graph-prediction-move-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("knowledge_graph.prediction_move_consumer_main")  # type: ignore[no-any-return]
    log.info("prediction_move_consumer_starting", service="knowledge-graph")

    # F-005 / BP-704: stall-aware liveness probe on the metrics port.
    liveness_probe = make_liveness_probe()
    metrics_handle = start_metrics_server(
        service_name="knowledge-graph-prediction-move-consumer",
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

    # PLAN-0056 Wave D2: the emitter turns each material move into per-entity signals.
    signal_emitter = PredictionSignalEmitter(
        emit_new_market=settings.prediction_signal_emit_new_market,
        new_market_base=settings.prediction_signal_new_market_base,
        resolution_base=settings.prediction_signal_resolution_base,
        material_move_adverse_factor=settings.prediction_signal_material_move_adverse_factor,
    )

    config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id="kg-prediction-move-group",
        topics=["market.prediction.move.v1"],
        group_instance_id=settings.kafka_prediction_move_consumer_instance_id,
    )
    consumer = PredictionMoveConsumer(
        config=config,
        session_factory=write_factory,
        signal_emitter=signal_emitter,
        dedup_client=valkey,
    )
    liveness_probe.bind(consumer)

    log_runtime_banner(
        "knowledge-graph-prediction-move-consumer",
        dependencies={
            "postgres_dsn": str(settings.database_url),
            "kafka_brokers": settings.kafka_bootstrap_servers,
            "valkey_url": getattr(settings, "valkey_url", None),
            "topics_subscribed": ["market.prediction.move.v1"],
        },
    )

    try:
        await run_consumer_supervised(consumer, stop_event, liveness_probe=liveness_probe)
    except ConsumerExited as exc:
        log.error("prediction_move_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    except Exception as exc:
        log.error("prediction_move_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    finally:
        await valkey.close()
        await engine.dispose()
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()
        log.info("prediction_move_consumer_stopped")


if __name__ == "__main__":
    asyncio.run(main())
