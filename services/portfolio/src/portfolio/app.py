"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import prometheus_client
import structlog.contextvars
from fastapi import FastAPI, Request, Response
from fastapi.responses import Response as FastAPIResponse
from starlette.middleware.base import BaseHTTPMiddleware

from observability import configure_logging, configure_tracing, get_logger  # type: ignore[import-untyped]
from observability.metrics import add_prometheus_middleware, create_metrics  # type: ignore[import-untyped]
from observability.sentry import SentrySettings, init_sentry  # type: ignore[import-untyped]
from observability.tracing import add_otel_middleware  # type: ignore[import-untyped]
from portfolio.api.exception_handlers import domain_error_handler, unhandled_exception_handler
from portfolio.api.internal import internal_router
from portfolio.api.routes import api_router
from portfolio.api.routes.provision import provision_router
from portfolio.config import Settings
from portfolio.domain.errors import DomainError
from portfolio.infrastructure.db.session import _build_factories
from portfolio.infrastructure.middleware.internal_jwt import InternalJWTMiddleware

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

logger = get_logger(__name__)  # type: ignore[no-any-return]


_VALID_REQUEST_ID_RE = re.compile(r"^[a-zA-Z0-9\-]{1,64}$")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Propagate X-Request-ID through the request lifecycle.

    Validates the incoming header: only alphanumeric + hyphens, max 64 chars.
    Invalid or missing values are replaced with a fresh ULID.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        import common.ids

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

    # 2. Tracing config (optional — middleware already registered in create_app)
    if settings.otlp_endpoint:
        configure_tracing(service_name=settings.service_name, otlp_endpoint=settings.otlp_endpoint)

    # 2b. Sentry — fourth observability pillar (default-off: SENTRY_ENABLED=false)
    init_sentry(service_name=settings.service_name, settings=SentrySettings())

    logger.info("portfolio_service_starting", service=settings.service_name)  # type: ignore[no-any-return]

    # 3. Start InternalJWTMiddleware — fetch JWKS from S9 at startup
    jwt_middleware: InternalJWTMiddleware | None = getattr(app.state, "_jwt_middleware", None)
    if jwt_middleware is not None:
        await jwt_middleware.startup()

    # 4. Create DB session factories (R23 — write + read split)
    engine, read_engine, write_factory, read_factory = _build_factories(settings)
    app.state.session_factory = write_factory  # backward-compat alias
    app.state.write_factory = write_factory
    app.state.read_factory = read_factory
    app.state.engine = engine
    app.state.read_engine = read_engine

    # 5. Build SnapTrade Fernet cipher (AD-3 — encrypt snaptrade_user_secret at rest).
    # If the key is empty (dev mode), cipher is None and secrets are stored as plaintext.
    if settings.snaptrade_secret_encryption_key:
        from cryptography.fernet import Fernet  # type: ignore[import-untyped]

        app.state.snaptrade_cipher = Fernet(settings.snaptrade_secret_encryption_key.encode())
    else:
        app.state.snaptrade_cipher = None

    # 6. Create SnapTrade brokerage client (PRD-0022)
    from portfolio.infrastructure.brokerage.snaptrade_client import SnapTradeClient

    app.state.brokerage_client = SnapTradeClient(
        client_id=settings.snaptrade_client_id.get_secret_value(),
        consumer_key=settings.snaptrade_consumer_key.get_secret_value(),
    )

    # 7. Create Valkey client for watchlist reverse-index cache
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

    valkey_client = ValkeyClient(url=settings.valkey_url)
    app.state.valkey_client = valkey_client

    # 7b. PLAN-0046 Wave 5 / T-46-5-02 — current-price REST client.
    # WHY one shared httpx.AsyncClient on app.state: connection pooling
    # across requests amortises TCP/TLS setup. The client lifetime is
    # bound to the FastAPI app lifespan (closed on shutdown below).
    import httpx as _httpx

    from portfolio.infrastructure.market_data.current_price_client import HttpCurrentPriceClient

    market_data_http = _httpx.AsyncClient(timeout=10.0)
    app.state.market_data_http = market_data_http
    app.state.current_price_client = HttpCurrentPriceClient(
        http=market_data_http,
        market_data_url=settings.market_data_service_url,
    )

    # 8. Create outbox dispatcher
    from portfolio.infrastructure.messaging.outbox.dispatcher import create_dispatcher

    dispatcher = create_dispatcher(settings, write_factory)
    app.state.dispatcher = dispatcher

    # Note: InstrumentEventConsumer runs as a separate process (portfolio-instrument-consumer).
    # See services/portfolio/src/portfolio/infrastructure/messaging/consumers/instrument_consumer_main.py

    logger.info("portfolio_service_started", service=settings.service_name)  # type: ignore[no-any-return]

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("portfolio_service_stopping", service=settings.service_name)  # type: ignore[no-any-return]

    # Stop dispatcher (if running)
    if hasattr(dispatcher, "stop"):
        dispatcher.stop()

    # Close Valkey client
    await valkey_client.close()

    # Close shared market-data HTTP client (PLAN-0046 Wave 5)
    await market_data_http.aclose()

    # Dispose engine(s) — read_engine only disposed separately if it is a distinct object
    await engine.dispose()
    if read_engine is not engine:
        await read_engine.dispose()
    logger.info("portfolio_service_stopped", service=settings.service_name)  # type: ignore[no-any-return]


def create_app() -> FastAPI:
    settings = Settings()  # type: ignore[call-arg]
    app = FastAPI(
        title="portfolio",
        version="2025.6.0",
        lifespan=lifespan,
    )
    app.state.settings = settings

    # InternalJWTMiddleware (RS256 verifier — PRD-0025 Wave C)
    # We store the instance on app.state so lifespan can call startup() on it.
    # startup() writes the public key to app.state._internal_jwt_public_key so the
    # separate middleware stack instance (created by add_middleware) can read it in dispatch().
    jwks_url = f"{settings.api_gateway_url}/internal/jwks"
    jwt_middleware = InternalJWTMiddleware(
        app,
        jwks_url=jwks_url,
        issuer=settings.internal_jwt_issuer,
        skip_verification=settings.internal_jwt_skip_verification,
    )
    app.state._jwt_middleware = jwt_middleware
    app.add_middleware(
        InternalJWTMiddleware,
        jwks_url=jwks_url,
        issuer=settings.internal_jwt_issuer,
        skip_verification=settings.internal_jwt_skip_verification,
    )

    # Middleware — must be registered before app starts (Starlette requirement)
    app.add_middleware(RequestIdMiddleware)
    metrics = create_metrics(service_name=settings.service_name)
    add_prometheus_middleware(app, metrics)
    add_otel_middleware(app)
    app.state.metrics = metrics

    # Exception handlers
    app.add_exception_handler(DomainError, domain_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # API routes
    app.include_router(api_router)
    app.include_router(internal_router)
    app.include_router(provision_router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", response_model=None)
    async def readyz() -> FastAPIResponse:
        """Check readiness by probing the database and JWKS with a 2-second timeout."""
        import json as _json

        from sqlalchemy import text

        # F-003B: JWKS public key must be loaded before accepting traffic.
        if getattr(app.state, "_internal_jwt_public_key", None) is None:
            return FastAPIResponse(
                content=_json.dumps({"status": "unavailable", "reason": "jwks_not_loaded"}),
                status_code=503,
                media_type="application/json",
            )

        engine = getattr(app.state, "engine", None)
        if engine is None:
            return FastAPIResponse(
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
            return FastAPIResponse(
                content='{"status": "unavailable", "reason": "db"}',
                status_code=503,
                media_type="application/json",
            )
        return FastAPIResponse(
            content='{"status": "ok"}',
            status_code=200,
            media_type="application/json",
        )

    @app.get("/metrics")
    async def metrics_endpoint() -> FastAPIResponse:
        """Prometheus metrics — protected by InternalJWTMiddleware (M-004)."""
        data = prometheus_client.generate_latest()
        return FastAPIResponse(content=data, media_type=prometheus_client.CONTENT_TYPE_LATEST)

    return app
