"""FastAPI application factory for the API Gateway (S9)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import httpx
from fastapi import FastAPI

from api_gateway.clients import ServiceClients
from api_gateway.config import Settings
from api_gateway.middleware import AuthMiddleware, add_cors
from api_gateway.routes import router

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage httpx client pool lifecycle."""
    settings: Settings = app.state.settings

    # Build downstream clients
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

    # Optional Valkey connection
    valkey_client = None
    try:
        import redis.asyncio as aioredis

        valkey_client = aioredis.from_url(settings.valkey_url)
        await valkey_client.ping()
    except Exception:
        valkey_client = None  # fail-open: rate limiting disabled

    app.state.valkey = valkey_client

    yield

    # Shutdown: close all clients
    for field_name in ServiceClients.__dataclass_fields__:
        client = getattr(clients, field_name)
        await client.aclose()
    if valkey_client:
        await valkey_client.aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = settings or Settings()

    app = FastAPI(
        title="worldview-gateway",
        version="2025.6.0",
        lifespan=lifespan,
    )
    app.state.settings = settings

    # Middleware (order matters: last added = first executed)
    add_cors(app, settings.cors_origins)
    app.add_middleware(
        AuthMiddleware,
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    # Routes
    app.include_router(router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics() -> dict[str, str]:
        return {"status": "stub"}

    return app
