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
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from alert.api import dlq, email_routes, health, routes
from alert.config import Settings
from alert.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
from observability import (  # type: ignore[import-untyped]
    assert_app_env_or_die,
    configure_logging,
    get_logger,
    register_error_handlers,
)
from observability.metrics import add_prometheus_middleware, create_metrics  # type: ignore[import-untyped]
from observability.sentry import SentrySettings, init_sentry  # type: ignore[import-untyped]
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

    # 1aa. Boot-time security guard (PLAN-0093 Wave A-1 / F-LOG-JWT-001).
    # Refuses to start when JWT verification is disabled AND APP_ENV is unset.
    assert_app_env_or_die(
        service_name=settings.service_name,
        internal_jwt_skip_verification=settings.internal_jwt_skip_verification,
    )

    # 1a. InternalJWT middleware startup — fetch JWKS from S9 (PRD-0025 T-D-1-08).
    # BP-159: serving instance created by add_middleware() wraps the inner stack, so
    # self.app != FastAPI app and self.app.state is unreachable. The startup call here
    # populates app.state._internal_jwt_public_key which dispatch() reads via request.app.state.
    jwt_mw = InternalJWTMiddleware(
        app,
        jwks_url=f"{settings.api_gateway_url}/internal/jwks",
        skip_verification=settings.internal_jwt_skip_verification,
        jti_replay_check_enabled=settings.jti_replay_check_enabled,
    )
    await jwt_mw.startup()

    # 2. Tracing (conditional — middleware registered in create_app)
    if settings.otlp_endpoint:
        configure_tracing(
            service_name=settings.service_name,
            otlp_endpoint=settings.otlp_endpoint,
        )

    # 2b. Sentry — fourth observability pillar (default-off: SENTRY_ENABLED=false)
    init_sentry(service_name=settings.service_name, settings=SentrySettings())

    # 3. Database — R23 dual factory (write + read)
    from alert.infrastructure.db.session import _build_factories

    engine, read_engine, write_factory, read_factory = _build_factories(settings)
    app.state.engine = engine
    app.state.read_engine = read_engine
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

    # 7. WebSocket connection manager — pass metrics so connect/disconnect update
    # the websocket_active_connections gauge (enabled via include_websocket=True above).
    from alert.infrastructure.websocket.manager import ConnectionManager

    ws_manager = ConnectionManager(metrics=app.state.metrics)
    app.state.ws_manager = ws_manager

    # 8. Kafka health producer (lightweight — for /readyz Kafka connectivity check)
    from confluent_kafka import Producer as _KafkaProducer  # type: ignore[import-untyped]

    kafka_health_producer = _KafkaProducer(
        {
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            # Larger socket timeout so the background connect thread succeeds before
            # list_topics(timeout=8) fires on the first /readyz call (BP-350).
            "socket.timeout.ms": "10000",
            "message.timeout.ms": "10000",
        }
    )
    app.state.kafka_health_producer = kafka_health_producer

    log.info("service_started", service=settings.service_name)  # type: ignore[no-any-return]
    yield

    # Shutdown
    await s1_client.close()
    await valkey.close()
    await engine.dispose()
    if read_engine is not engine:
        await read_engine.dispose()
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

    # Exception handlers — must be registered before middleware so that handler
    # responses are still processed by middleware layers (e.g. Prometheus timing).
    register_error_handlers(app)

    # PLAN-0087 (2026-05-09): CORS for browser WS connections from worldview-web.
    # uvicorn rejects WS upgrades from cross-origin browsers with 403 before any
    # route handler runs without this middleware (observed on /api/v1/alerts/stream).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3001",
            "http://localhost:3000",
            "http://127.0.0.1:3001",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Middleware (must register before app starts)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        InternalJWTMiddleware,
        jwks_url=f"{settings.api_gateway_url}/internal/jwks",
        skip_verification=settings.internal_jwt_skip_verification,
        jti_replay_check_enabled=settings.jti_replay_check_enabled,
    )
    metrics: Any = create_metrics(service_name=settings.service_name, include_websocket=True)
    add_prometheus_middleware(app, metrics)
    add_otel_middleware(app)
    app.state.metrics = metrics

    # Routers
    app.include_router(health.router)
    app.include_router(routes.router)
    # PLAN-0094 follow-up: /internal/v1/* — service-caller endpoints.
    app.include_router(routes.internal_router)
    app.include_router(dlq.router)
    app.include_router(email_routes.router)

    return app
