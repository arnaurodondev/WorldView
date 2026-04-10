"""Standalone intelligence consumer entry point for the Alert service (S10).

Runs as an independent process (R22) with its own session factory, Valkey
dedup client, S1 REST client, and signal handling.

Consumes:
  - ``nlp.signal.detected.v1``
  - ``graph.state.changed.v1``
  - ``intelligence.contradiction.v1``

Run with::

    python -m alert.infrastructure.messaging.consumers.intelligence_consumer_main
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys

from observability import configure_logging, get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def main() -> None:
    from alert.application.use_cases.alert_fanout import AlertFanoutUseCase
    from alert.config import Settings
    from alert.domain.entities import SeverityThresholds
    from alert.infrastructure.cache.watchlist_cache import WatchlistCache
    from alert.infrastructure.clients.s1_client import S1Client
    from alert.infrastructure.db.repositories.alert import AlertRepository
    from alert.infrastructure.db.repositories.dedup import DedupRepository
    from alert.infrastructure.db.repositories.outbox import OutboxRepository
    from alert.infrastructure.db.repositories.pending_alert import PendingAlertRepository
    from alert.infrastructure.db.session import _build_factories
    from alert.infrastructure.messaging.consumers.intelligence_consumer import (
        IntelligenceConsumer,
    )
    from alert.infrastructure.notification.valkey_publisher import ValkeyNotificationPublisher
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]

    settings = Settings()
    configure_logging(
        service_name="alert-intelligence-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("alert.intelligence_consumer_main")  # type: ignore[no-any-return]
    log.info("intelligence_consumer_starting", service="alert")

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    # Database — write factory for fan-out (creates alerts, outbox events)
    _engine, _read_engine, write_factory, _read_factory = _build_factories(settings)

    # Valkey — dedup + watchlist cache
    valkey = create_valkey_client_from_url(settings.valkey_url)

    # S1 client — resolve watchers
    s1_client = S1Client(settings)

    # Watchlist cache
    watchlist_cache = WatchlistCache(valkey, s1_client, ttl=settings.watchlist_cache_ttl_seconds)  # type: ignore[arg-type]

    # Notification publisher — sends to Valkey pub/sub channel per user
    notification_publisher = ValkeyNotificationPublisher(valkey)

    # Build fan-out use case
    def _repo_factory(session):  # type: ignore[no-untyped-def]
        return (
            AlertRepository(session),
            PendingAlertRepository(session),
            DedupRepository(session),
            OutboxRepository(session),
        )

    fanout = AlertFanoutUseCase(
        session_factory=write_factory,
        watchlist_cache=watchlist_cache,
        notification_publisher=notification_publisher,
        repo_factory=_repo_factory,  # type: ignore[arg-type]
        dedup_window_seconds=settings.alert_dedup_window_seconds,
        alert_delivered_topic=settings.kafka_topic_alert_delivered,
        severity_thresholds=SeverityThresholds(
            critical=settings.alert_severity_critical_threshold,
            high=settings.alert_severity_high_threshold,
            medium=settings.alert_severity_medium_threshold,
        ),
    )

    # Consumer config
    config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_consumer_group,
        topics=[
            settings.kafka_topic_signal,
            settings.kafka_topic_graph_state,
            settings.kafka_topic_contradiction,
        ],
    )
    consumer = IntelligenceConsumer(
        config=config,
        fanout_use_case=fanout,
        dedup_client=valkey,
    )

    try:
        consumer_task = asyncio.create_task(consumer.run())
        await stop_event.wait()
        consumer.stop()
        try:
            await asyncio.wait_for(consumer_task, timeout=30.0)
        except TimeoutError:
            consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await consumer_task
    except Exception as exc:
        log.error("intelligence_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    else:
        log.info("intelligence_consumer_stopped")
    finally:
        await s1_client.close()
        await valkey.close()
        await _engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
