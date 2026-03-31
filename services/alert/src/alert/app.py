"""FastAPI application factory — Alert service (S10).

Observability wiring follows STANDARDS.md §5 (PLAN-0003 canonical pattern):
  1. configure_logging()         — always first in lifespan
  2. create_metrics() + add_prometheus_middleware() + app.state.metrics
  3. configure_tracing() (conditional) + add_otel_middleware()
  4. RequestIdMiddleware         — registered in create_app()
  5. GET /metrics endpoint       — in health router
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import structlog.contextvars
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from alert.api import dlq, health, routes
from alert.config import Settings
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
        import common.ids  # type: ignore[import-untyped]

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

    # 1. Logging — always first
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )
    log = get_logger("alert.app")  # type: ignore[no-any-return]

    # 2. Tracing (conditional — middleware registered in create_app)
    if settings.otlp_endpoint:
        configure_tracing(
            service_name=settings.service_name,
            otlp_endpoint=settings.otlp_endpoint,
        )

    # 3. Database — R23 dual factory (write + read)
    from alert.infrastructure.db.session import _build_factories

    engine, write_factory, read_factory = _build_factories(settings)
    app.state.engine = engine
    app.state.session_factory = write_factory
    app.state.write_factory = write_factory
    app.state.read_factory = read_factory

    # 4. Valkey
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]

    valkey = create_valkey_client_from_url(settings.valkey_url)
    app.state.valkey = valkey

    # 5. S1 client
    from alert.infrastructure.clients.s1_client import S1Client

    s1_client = S1Client(settings)
    app.state.s1_client = s1_client

    # 6. Watchlist cache
    from alert.infrastructure.cache.watchlist_cache import WatchlistCache

    watchlist_cache = WatchlistCache(valkey, s1_client, ttl=settings.watchlist_cache_ttl_seconds)  # type: ignore[arg-type]
    app.state.watchlist_cache = watchlist_cache

    # 7. WebSocket connection manager
    from alert.infrastructure.websocket.manager import ConnectionManager

    ws_manager = ConnectionManager()
    app.state.ws_manager = ws_manager

    log.info("service_started", service=settings.service_name)  # type: ignore[no-any-return]
    yield

    # Shutdown
    await s1_client.close()
    await valkey.close()
    await engine.dispose()
    log.info("service_stopped", service=settings.service_name)  # type: ignore[no-any-return]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="alert-service",
        version="2025.6.0",
        lifespan=lifespan,
    )
    settings = settings or Settings()
    app.state.settings = settings

    # Middleware (must register before app starts)
    app.add_middleware(RequestIdMiddleware)
    metrics: Any = create_metrics(service_name=settings.service_name)
    add_prometheus_middleware(app, metrics)
    add_otel_middleware(app)
    app.state.metrics = metrics

    # Routers
    app.include_router(health.router)
    app.include_router(routes.router)
    app.include_router(dlq.router)

    return app


app = create_app()
