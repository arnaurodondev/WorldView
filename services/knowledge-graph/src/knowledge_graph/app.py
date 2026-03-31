"""FastAPI application factory — knowledge-graph service (S7).

Lifespan wiring (PLAN-0003 / STANDARDS.md §5 canonical pattern):
  1. configure_logging()                  — always first
  2. create_metrics() + middleware        — Prometheus
  3. configure_tracing() (optional)       — OTel if otlp_endpoint set
  4. intelligence_db session factories   — read/write + read-only
  5. Kafka producer + consumers          — enriched, entity, instrument, fundamentals
  6. KnowledgeGraphScheduler             — APScheduler (8 jobs) + consumer co-topology
  7. OutboxDispatcher                    — polls outbox_events, publishes to Kafka
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import structlog.contextvars
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

import common.ids  # type: ignore[import-untyped]
from knowledge_graph.api import dlq, health, routes
from knowledge_graph.config import Settings
from knowledge_graph.domain.errors import KnowledgeGraphError
from knowledge_graph.infrastructure.intelligence_db.session import (
    _build_factories as _build_intel_factories,
)
from observability import configure_logging, get_logger  # type: ignore[import-untyped]
from observability.metrics import add_prometheus_middleware, create_metrics  # type: ignore[import-untyped]
from observability.tracing import add_otel_middleware, configure_tracing  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

_VALID_REQUEST_ID_RE = re.compile(r"^[a-zA-Z0-9\-]{1,64}$")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Propagate X-Request-ID through the request lifecycle."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        raw_id = request.headers.get("X-Request-ID", "")
        request_id = raw_id if _VALID_REQUEST_ID_RE.match(raw_id) else common.ids.new_ulid()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = str(request_id)
        structlog.contextvars.clear_contextvars()
        return response


async def _supervised_dispatcher(dispatcher: Any, app: FastAPI) -> None:
    """Restart the outbox dispatcher on crash with exponential backoff."""
    log = get_logger("knowledge_graph.app")
    failures = 0
    while True:
        try:
            await dispatcher.run_forever()
            break
        except asyncio.CancelledError:
            raise
        except Exception:
            failures += 1
            delay = min(5 * (2**failures), 300)
            log.exception(
                "kg_dispatcher_crashed",
                restart_delay=delay,
                consecutive_failures=failures,
            )
            app.state.dispatcher_healthy = False
            await asyncio.sleep(delay)
            app.state.dispatcher_healthy = True


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings

    # 1. Logging — always first (STANDARDS.md §5)
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )
    log = get_logger("knowledge_graph.app")

    # 2. Tracing (conditional — middleware registered in create_app)
    if settings.otlp_endpoint:
        configure_tracing(
            service_name=settings.service_name,
            otlp_endpoint=settings.otlp_endpoint,
        )

    # 3. intelligence_db session factories — R23 dual factory (write + read)
    engine, write_factory, read_factory = _build_intel_factories(settings)
    session_factory = write_factory  # local alias for downstream wiring
    app.state.session_factory = write_factory
    app.state.write_factory = write_factory
    app.state.read_factory = read_factory
    app.state.readonly_session_factory = read_factory
    app.state.engine = engine

    # 4. Admin token (DLQ endpoint auth)
    app.state.admin_token = getattr(settings, "admin_token", "")

    dispatch_task: asyncio.Task[Any] | None = None
    scheduler = None

    try:
        # 5. Outbox dispatcher (needs Kafka producer — best-effort in non-infra runs)
        try:
            from confluent_kafka import Producer  # type: ignore[import-untyped]

            from knowledge_graph.infrastructure.outbox.dispatcher import OutboxDispatcher

            producer = Producer(
                {
                    "bootstrap.servers": settings.kafka_bootstrap_servers,
                }
            )
            dispatcher = OutboxDispatcher(
                session_factory=session_factory,
                producer=producer,  # type: ignore[arg-type]
                poll_interval_s=settings.dispatcher_poll_interval_s,
                batch_size=settings.dispatcher_batch_size,
            )
            app.state.dispatcher = dispatcher
            app.state.dispatcher_healthy = True
            dispatch_task = asyncio.create_task(_supervised_dispatcher(dispatcher, app), name="kg_outbox_dispatcher")
        except Exception:
            log.warning("kg_dispatcher_init_failed_no_kafka", exc_info=True)
            app.state.dispatcher_healthy = False

        # 6. APScheduler + consumer co-topology (best-effort — needs Kafka + ML)
        try:
            from knowledge_graph.infrastructure.scheduler.scheduler import (
                KnowledgeGraphScheduler,
                build_workers,
            )

            workers = build_workers(settings, session_factory)
            scheduler = KnowledgeGraphScheduler(settings, workers=workers)
            app.state.scheduler = scheduler

            # Consumer requires full Kafka + embedding client — best-effort
            async def _consumer_stub() -> None:
                """Placeholder until consumer is wired with Kafka producer + ML client."""
                log.warning("kg_consumer_not_started_missing_kafka_or_ml")

            await scheduler.start(_consumer_stub())
        except Exception:
            log.warning("kg_scheduler_init_failed", exc_info=True)

        log.info("knowledge_graph_started", service=settings.service_name)
        yield

    finally:
        # Shutdown in reverse order
        if scheduler is not None:
            await scheduler.stop()

        if dispatch_task is not None and not dispatch_task.done():
            dispatch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await dispatch_task

        await engine.dispose()
        log.info("knowledge_graph_stopped", service=settings.service_name)


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(KnowledgeGraphError)
    async def _domain_error(_request: Request, exc: KnowledgeGraphError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": "domain_error", "detail": str(exc)})

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        get_logger("knowledge_graph.app").exception("unhandled_error", error=str(exc))
        return JSONResponse(status_code=500, content={"error": "internal_error"})


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = settings or Settings()

    app = FastAPI(
        title="knowledge-graph",
        version="2025.6.0",
        lifespan=lifespan,
    )
    app.state.settings = settings

    # Middleware (must be registered before app starts)
    app.add_middleware(RequestIdMiddleware)
    metrics = create_metrics(service_name=settings.service_name)
    add_prometheus_middleware(app, metrics)
    add_otel_middleware(app)
    app.state.metrics = metrics

    _register_exception_handlers(app)

    app.include_router(health.router, tags=["health"])
    app.include_router(routes.router)
    app.include_router(dlq.router)

    return app
