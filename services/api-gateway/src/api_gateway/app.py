"""FastAPI application factory for the API Gateway."""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import httpx
import prometheus_client
import structlog.contextvars
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from api_gateway.clients import ServiceClients
from api_gateway.config import Settings
from api_gateway.middleware import (
    InternalJWTIssuerMiddleware,
    OIDCAuthMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    add_cors,
)
from api_gateway.routes import auth_router
from api_gateway.routes import router as main_router
from api_gateway.routes.admin_costs import router as admin_costs_router
from api_gateway.routes.health import router as health_router
from api_gateway.routes.internal import router as internal_router
from messaging.valkey import ValkeyClient, create_valkey_client_from_url  # type: ignore[import-untyped]
from observability import configure_logging, get_logger  # type: ignore[import-untyped]
from observability.metrics import add_prometheus_middleware, create_metrics  # type: ignore[import-untyped]
from observability.tracing import add_otel_middleware, configure_tracing  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable


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
    """Manage application lifecycle: observability → OIDC discovery → RSA keys → clients → Valkey."""
    settings: Settings = app.state.settings

    # 1. Logging — always first
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )
    logger = get_logger("api_gateway.app")

    # 2. Tracing config (optional)
    if settings.otlp_endpoint:
        configure_tracing(
            service_name=settings.service_name,
            otlp_endpoint=settings.otlp_endpoint,
        )

    # 3. Shared httpx client for OIDC discovery (and S1 provisioning calls)
    httpx_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))
    app.state.httpx_client = httpx_client

    # 4. OIDC discovery — fail-fast if unavailable (service cannot function without it).
    # In test/dev environments where Zitadel is not running, set
    # API_GATEWAY_OIDC_DISCOVERY_OPTIONAL=true to start with internal-JWT-only auth.
    from api_gateway.oidc import (
        build_jwks_response,
        fetch_oidc_discovery,
        load_rsa_private_key,
        rsa_key_id,
    )

    try:
        oidc_config = await fetch_oidc_discovery(settings.oidc_issuer_url, httpx_client)
        app.state.oidc_config = oidc_config
        logger.info("oidc_discovery_complete", issuer=oidc_config.issuer)
    except Exception as exc:
        if settings.oidc_discovery_optional:
            app.state.oidc_config = None
            logger.warning(
                "oidc_discovery_skipped",
                error=str(exc),
                detail="OIDC_DISCOVERY_OPTIONAL=true; starting with internal-JWT-only auth",
            )
        else:
            logger.error("oidc_discovery_failed", error=str(exc))
            raise RuntimeError(f"OIDC discovery failed at startup: {exc}") from exc

    # 5. RSA keypair for internal JWT signing
    private_key = load_rsa_private_key(settings.internal_jwt_private_key.get_secret_value())
    public_key = private_key.public_key()
    kid = rsa_key_id(public_key)
    app.state.rsa_private_key = private_key
    app.state.rsa_public_key = public_key
    app.state.rsa_kid = kid
    app.state.internal_jwks = build_jwks_response(public_key, kid)
    logger.info("rsa_keypair_loaded", kid=kid)

    # 6. Downstream service clients
    timeout = httpx.Timeout(30.0, connect=5.0)
    clients = ServiceClients(
        portfolio=httpx.AsyncClient(base_url=settings.portfolio_url, timeout=timeout),
        market_data=httpx.AsyncClient(base_url=settings.market_data_url, timeout=timeout),
        market_ingestion=httpx.AsyncClient(base_url=settings.market_ingestion_url, timeout=timeout),
        content_ingestion=httpx.AsyncClient(base_url=settings.content_ingestion_url, timeout=timeout),
        content_store=httpx.AsyncClient(base_url=settings.content_store_url, timeout=timeout),
        nlp_pipeline=httpx.AsyncClient(base_url=settings.nlp_pipeline_url, timeout=timeout),
        knowledge_graph=httpx.AsyncClient(base_url=settings.knowledge_graph_url, timeout=timeout),
        rag_chat=httpx.AsyncClient(base_url=settings.rag_chat_url, timeout=timeout),
        alert=httpx.AsyncClient(base_url=settings.alert_url, timeout=timeout),
    )
    app.state.clients = clients

    # 7. Valkey (fail-open: rate limiting degrades gracefully if unavailable)
    valkey: ValkeyClient | None = None
    try:
        valkey = create_valkey_client_from_url(settings.valkey_url)
        await valkey.ping()
        app.state.valkey = valkey
        logger.info("valkey_connected", url=settings.valkey_url)
    except Exception as exc:
        app.state.valkey = None
        logger.warning("valkey_unavailable", error=str(exc), detail="rate limiting disabled")

    logger.info("service_started", service=settings.service_name)
    yield

    # Shutdown
    for field_name in ServiceClients.__dataclass_fields__:
        client = getattr(clients, field_name)
        await client.aclose()
    await httpx_client.aclose()
    if valkey is not None:
        await valkey.close()
    logger.info("service_stopped", service=settings.service_name)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = settings or Settings()  # type: ignore[call-arg]  # pydantic-settings reads required fields from env

    app = FastAPI(
        title="worldview-gateway",
        version="2025.6.0",
        lifespan=lifespan,
    )
    app.state.settings = settings

    # Middleware registration order (Starlette: last added = outermost for requests)
    # Request order: RequestId → SecurityHeaders → Prometheus → OTel → CORS → RateLimit → OIDCAuth → InternalJWT
    # InternalJWT innermost (after OIDCAuth) so request.state.user is set before JWT issuance.
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    metrics = create_metrics(service_name=settings.service_name)
    add_prometheus_middleware(app, metrics)
    add_otel_middleware(app)
    app.state.metrics = metrics
    add_cors(app, settings.cors_origins)
    # RateLimitMiddleware and OIDCAuthMiddleware access app.state in dispatch() — safe to register
    # with None/placeholder here; they read from app.state at request time after lifespan completes.
    app.add_middleware(
        RateLimitMiddleware,
        valkey_client=None,  # replaced by app.state.valkey at lifespan
        max_requests=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    # OIDCAuth must run before InternalJWT: OIDCAuth validates token + sets request.state.user;
    # InternalJWT then signs and attaches X-Internal-JWT using that user state.
    # Starlette: last-added = outermost (first to receive request).
    # So OIDCAuth is added last → outermost → runs first; InternalJWT added earlier → innermost → runs after.
    app.add_middleware(InternalJWTIssuerMiddleware)  # innermost of this pair — runs after OIDCAuth
    app.add_middleware(OIDCAuthMiddleware)  # outermost of this pair — runs first (last added)

    # Metrics endpoint
    @app.get("/metrics")
    async def metrics_endpoint() -> Response:
        data = prometheus_client.generate_latest()
        return Response(content=data, media_type=prometheus_client.CONTENT_TYPE_LATEST)

    # Routes
    app.include_router(health_router, tags=["health"])
    app.include_router(internal_router)
    app.include_router(auth_router)
    app.include_router(admin_costs_router)
    app.include_router(main_router)

    return app
