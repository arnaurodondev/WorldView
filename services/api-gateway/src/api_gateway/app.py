"""FastAPI application factory for the API Gateway."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import httpx
import prometheus_client
import structlog.contextvars
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from api_gateway.clients import ServiceClients
from api_gateway.config import Settings
from api_gateway.middleware import AuthMiddleware, add_cors
from api_gateway.routes import router as main_router
from api_gateway.routes.health import router as health_router
from messaging.valkey import ValkeyClient, create_valkey_client_from_url  # type: ignore[import-untyped]
from observability import configure_logging, get_logger  # type: ignore[import-untyped]
from observability.metrics import add_prometheus_middleware, create_metrics  # type: ignore[import-untyped]
from observability.tracing import add_otel_middleware, configure_tracing  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Propagate X-Request-ID through the request lifecycle."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        import common.ids

        request_id = request.headers.get("X-Request-ID") or common.ids.new_ulid()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = str(request_id)
        structlog.contextvars.clear_contextvars()
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application lifecycle: observability → clients → Valkey."""
    settings: Settings = app.state.settings

    # 1. Logging — always first
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )
    logger = get_logger("api_gateway.app")

    # 2. Tracing config (optional — middleware already registered in create_app)
    if settings.otlp_endpoint:
        configure_tracing(
            service_name=settings.service_name,
            otlp_endpoint=settings.otlp_endpoint,
        )

    # 3. Downstream service clients
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
    )
    app.state.clients = clients

    # 5. Valkey (fail-open: rate limiting degrades gracefully if unavailable)
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
    if valkey is not None:
        await valkey.close()
    logger.info("service_stopped", service=settings.service_name)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = settings or Settings()

    app = FastAPI(
        title="worldview-gateway",
        version="2025.6.0",
        lifespan=lifespan,
    )
    app.state.settings = settings

    # Middleware — must be registered before app starts (Starlette requirement)
    # Order: last added = outermost
    app.add_middleware(RequestIdMiddleware)
    metrics = create_metrics(service_name=settings.service_name)
    add_prometheus_middleware(app, metrics)
    add_otel_middleware(app)
    app.state.metrics = metrics
    add_cors(app, settings.cors_origins)
    app.add_middleware(
        AuthMiddleware,
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    # Metrics endpoint
    @app.get("/metrics")
    async def metrics_endpoint() -> Response:
        data = prometheus_client.generate_latest()
        return Response(content=data, media_type=prometheus_client.CONTENT_TYPE_LATEST)

    # Routes
    app.include_router(health_router, tags=["health"])
    app.include_router(main_router)

    return app
