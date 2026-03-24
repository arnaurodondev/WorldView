"""FastAPI application factory."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import prometheus_client
from fastapi import FastAPI
from fastapi.responses import Response

from observability import configure_logging, configure_tracing, get_logger  # type: ignore[import-untyped]
from observability.metrics import add_prometheus_middleware, create_metrics  # type: ignore[import-untyped]
from observability.tracing import add_otel_middleware  # type: ignore[import-untyped]
from portfolio.api.exception_handlers import domain_error_handler, unhandled_exception_handler
from portfolio.api.routes import api_router
from portfolio.config import Settings
from portfolio.domain.errors import DomainError
from portfolio.infrastructure.db.session import create_session_factory

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = get_logger(__name__)  # type: ignore[no-any-return]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings

    # 1. Configure logging and tracing
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )
    configure_tracing(service_name=settings.service_name, otlp_endpoint=settings.otlp_endpoint)

    logger.info("portfolio_service_starting", service=settings.service_name)  # type: ignore[no-any-return]

    # 2. Create DB session factory
    engine, session_factory = create_session_factory(settings.database_url)
    app.state.session_factory = session_factory
    app.state.engine = engine

    # 3. Create Valkey client for watchlist reverse-index cache
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

    valkey_client = ValkeyClient(url=settings.valkey_url)
    app.state.valkey_client = valkey_client

    # 4. Create outbox dispatcher
    from portfolio.infrastructure.messaging.outbox.dispatcher import create_dispatcher

    dispatcher = create_dispatcher(settings, session_factory)
    app.state.dispatcher = dispatcher

    # 5. Create instrument event consumer
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from portfolio.infrastructure.messaging.consumers.instrument_consumer import InstrumentEventConsumer

    consumer_config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.consumer_group_instrument,
        topics=[settings.topic_instrument_created, settings.topic_instrument_updated],
    )
    consumer = InstrumentEventConsumer(consumer_config, session_factory)
    app.state.consumer = consumer

    # Start consumer in background (non-blocking)
    consumer_task = asyncio.create_task(consumer.run())
    app.state.consumer_task = consumer_task

    logger.info("portfolio_service_started", service=settings.service_name)  # type: ignore[no-any-return]

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("portfolio_service_stopping", service=settings.service_name)  # type: ignore[no-any-return]

    # Stop consumer
    consumer.stop()
    try:
        await asyncio.wait_for(consumer_task, timeout=10.0)
    except (TimeoutError, asyncio.CancelledError):
        consumer_task.cancel()

    # Stop dispatcher (if running)
    if hasattr(dispatcher, "stop"):
        dispatcher.stop()

    # Close Valkey client
    await valkey_client.close()

    # Dispose engine
    await engine.dispose()
    logger.info("portfolio_service_stopped", service=settings.service_name)  # type: ignore[no-any-return]


def create_app() -> FastAPI:
    settings = Settings()
    app = FastAPI(
        title="portfolio",
        version="2025.6.0",
        lifespan=lifespan,
    )
    app.state.settings = settings

    # Exception handlers
    app.add_exception_handler(DomainError, domain_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # Observability middleware
    metrics = create_metrics(settings.service_name)
    add_prometheus_middleware(app, metrics)
    add_otel_middleware(app)

    # API routes
    app.include_router(api_router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", response_model=None)
    async def readyz() -> Response:
        """Check readiness by probing the database with a 2-second timeout."""
        from sqlalchemy import text

        engine = getattr(app.state, "engine", None)
        if engine is None:
            return Response(
                content='{"status": "unavailable", "reason": "db"}',
                status_code=503,
                media_type="application/json",
            )
        try:

            async def _probe() -> None:
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))

            await asyncio.wait_for(_probe(), timeout=2.0)
        except Exception:
            return Response(
                content='{"status": "unavailable", "reason": "db"}',
                status_code=503,
                media_type="application/json",
            )
        return Response(
            content='{"status": "ok"}',
            status_code=200,
            media_type="application/json",
        )

    @app.get("/metrics")
    async def metrics_endpoint() -> Response:
        data = prometheus_client.generate_latest()
        return Response(content=data, media_type=prometheus_client.CONTENT_TYPE_LATEST)

    return app
