"""Entry point for the Alert service (S10).

Starts:
  - 2 Kafka consumers (IntelligenceConsumer + WatchlistConsumer)
  - 1 Outbox dispatcher (AlertOutboxDispatcher)
  - FastAPI app via uvicorn (includes WebSocket manager)

Run with:
    python -m alert.main
or:
    uvicorn alert.app:app --host 0.0.0.0 --port 8010
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys

import uvicorn
from alert.app import create_app
from alert.config import Settings

from observability import configure_logging, get_logger  # type: ignore[import-untyped]


async def _run_intelligence_consumer(settings: Settings, app_state: object) -> None:
    """Run IntelligenceConsumer until stop signal."""
    from alert.infrastructure.messaging.consumers.intelligence_consumer import IntelligenceConsumer

    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_consumer_group,
        topics=[
            settings.kafka_topic_signal,
            settings.kafka_topic_graph_state,
            settings.kafka_topic_contradiction,
        ],
    )
    fanout = getattr(app_state, "fanout_use_case", None)
    if fanout is None:
        return
    consumer = IntelligenceConsumer(config=config, fanout_use_case=fanout)
    await consumer.run()


async def _run_watchlist_consumer(settings: Settings, app_state: object) -> None:
    """Run WatchlistConsumer until stop signal."""
    from alert.infrastructure.messaging.consumers.watchlist_consumer import WatchlistConsumer

    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_watchlist_consumer_group,
        topics=[settings.kafka_topic_watchlist],
    )
    cache = getattr(app_state, "watchlist_cache", None)
    if cache is None:
        return
    consumer = WatchlistConsumer(config=config, watchlist_cache=cache)
    await consumer.run()


async def _run_dispatcher(app_state: object) -> None:
    """Run the outbox dispatcher until stop."""
    dispatcher = getattr(app_state, "dispatcher", None)
    if dispatcher is None:
        return
    await dispatcher.run()


async def main() -> None:
    settings = Settings()
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )
    log = get_logger("alert.main")  # type: ignore[no-any-return]

    app = create_app(settings)
    config = uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        log_config=None,  # structlog handles logging
    )
    server = uvicorn.Server(config)

    # Graceful shutdown on SIGTERM/SIGINT
    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("signal_received", signal=sig)  # type: ignore[no-any-return]
        stop_event.set()
        server.should_exit = True

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    # Start uvicorn (which manages the app lifespan)
    server_task = asyncio.create_task(server.serve())

    # Start consumers and dispatcher after app state is initialised
    # (consumers need app_state.fanout_use_case / watchlist_cache)
    await asyncio.sleep(1)  # brief pause for lifespan to complete

    from alert.application.use_cases.alert_fanout import AlertFanoutUseCase
    from alert.infrastructure.clients.s7_entity_resolver import S7EntityResolver
    from alert.infrastructure.db.repositories.alert import AlertRepository
    from alert.infrastructure.db.repositories.dedup import DedupRepository
    from alert.infrastructure.db.repositories.outbox import OutboxRepository
    from alert.infrastructure.db.repositories.pending_alert import PendingAlertRepository

    def _repo_factory(session):  # type: ignore[no-untyped-def]
        return (
            AlertRepository(session),
            PendingAlertRepository(session),
            DedupRepository(session),
            OutboxRepository(session),
        )

    session_factory = app.state.session_factory
    watchlist_cache = app.state.watchlist_cache
    ws_manager = app.state.ws_manager
    # WHY pull valkey from app.state: lifespan creates it once and reuses for
    # both watchlist cache + (now) entity resolver. Avoids opening a second
    # connection pool for the same Valkey URL.
    valkey = app.state.valkey
    entity_resolver = S7EntityResolver(settings, valkey)
    app.state.entity_resolver = entity_resolver

    fanout = AlertFanoutUseCase(
        session_factory=session_factory,
        watchlist_cache=watchlist_cache,
        notification_publisher=ws_manager,
        repo_factory=_repo_factory,  # type: ignore[arg-type]
        dedup_window_seconds=settings.alert_dedup_window_seconds,
        alert_delivered_topic=settings.kafka_topic_alert_delivered,
        entity_resolver=entity_resolver,
    )
    app.state.fanout_use_case = fanout

    consumer_tasks = [
        asyncio.create_task(_run_intelligence_consumer(settings, app.state)),
        asyncio.create_task(_run_watchlist_consumer(settings, app.state)),
        asyncio.create_task(_run_dispatcher(app.state)),
    ]

    log.info("consumers_started")  # type: ignore[no-any-return]

    await stop_event.wait()

    # Cancel consumers
    for task in consumer_tasks:
        task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.gather(*consumer_tasks, return_exceptions=True)

    await server_task
    log.info("alert_service_stopped")  # type: ignore[no-any-return]


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
