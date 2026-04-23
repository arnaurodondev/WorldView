"""FastAPI application factory — knowledge-graph service (S7).

Lifespan wiring (PLAN-0003 / STANDARDS.md §5 canonical pattern):
  1. configure_logging()                  — always first
  2. create_metrics() + middleware        — Prometheus
  3. configure_tracing() (optional)       — OTel if otlp_endpoint set
  4. intelligence_db session factories   — read/write + read-only

Background processes run as standalone entry points (R22 / PLAN-0011 Wave C-3):
  - knowledge_graph.infrastructure.messaging.outbox.dispatcher_main
  - knowledge_graph.infrastructure.scheduler.scheduler_main
  - knowledge_graph.infrastructure.messaging.consumers.enriched_consumer_main
  - knowledge_graph.infrastructure.messaging.consumers.entity_consumer_main
  - knowledge_graph.infrastructure.messaging.consumers.fundamentals_consumer_main
  - knowledge_graph.infrastructure.messaging.consumers.instrument_consumer_main
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import structlog.contextvars
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

import common.ids  # type: ignore[import-untyped]
from knowledge_graph.api import (
    claims,
    cypher,
    dlq,
    entities,
    events,
    health,
    internal_costs,
    routes,
    search,
    temporal_events,
)
from knowledge_graph.config import Settings
from knowledge_graph.domain.errors import KnowledgeGraphError
from knowledge_graph.infrastructure.intelligence_db.session import (
    _build_factories as _build_intel_factories,
)
from knowledge_graph.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
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

    # 3. Start InternalJWTMiddleware — fetch JWKS from S9 at startup
    jwt_middleware: InternalJWTMiddleware | None = getattr(app.state, "_jwt_middleware", None)
    if jwt_middleware is not None:
        await jwt_middleware.startup()

    # 4. intelligence_db session factories — R23 dual factory (write + read)
    engine, read_engine, write_factory, read_factory = _build_intel_factories(settings)
    app.state.session_factory = write_factory
    app.state.write_factory = write_factory
    app.state.read_factory = read_factory
    app.state.readonly_session_factory = read_factory
    app.state.engine = engine
    app.state.read_engine = read_engine

    # 4. Admin token (DLQ endpoint auth)
    app.state.admin_token = getattr(settings, "admin_token", "")

    try:
        log.info("knowledge_graph_started", service=settings.service_name)
        yield
    finally:
        await engine.dispose()
        if read_engine is not engine:
            await read_engine.dispose()
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
    settings = settings or Settings()  # type: ignore[call-arg]

    app = FastAPI(
        title="knowledge-graph",
        version="2025.6.0",
        lifespan=lifespan,
    )
    app.state.settings = settings

    # InternalJWTMiddleware (RS256 verifier — PRD-0025 Wave D)
    # We store the instance on app.state so lifespan can call startup() on it.
    jwks_url = f"{settings.api_gateway_url}/internal/jwks"
    jwt_middleware = InternalJWTMiddleware(
        app,
        jwks_url=jwks_url,
        skip_verification=settings.internal_jwt_skip_verification,
    )
    app.state._jwt_middleware = jwt_middleware
    app.add_middleware(
        InternalJWTMiddleware,
        jwks_url=jwks_url,
        skip_verification=settings.internal_jwt_skip_verification,
    )

    # Middleware (must be registered before app starts)
    app.add_middleware(RequestIdMiddleware)
    metrics = create_metrics(service_name=settings.service_name)
    add_prometheus_middleware(app, metrics)
    add_otel_middleware(app)
    app.state.metrics = metrics

    _register_exception_handlers(app)

    app.include_router(health.router, tags=["health"])
    app.include_router(routes.router)
    app.include_router(claims.router)
    app.include_router(entities.router)
    app.include_router(events.router)
    app.include_router(search.router)
    app.include_router(temporal_events.router)
    app.include_router(cypher.router)
    app.include_router(dlq.router)
    app.include_router(internal_costs.router)

    return app
