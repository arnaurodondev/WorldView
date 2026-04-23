"""FastAPI application factory — NLP Pipeline service (S6).

Background processes (consumers, dispatcher) run as standalone entry points
per R22 — see ``dispatcher_main.py``, ``article_consumer_main.py``, and
``watchlist_consumer_main.py`` under ``infrastructure/messaging/``.

Lifespan sequence (STANDARDS.md §5):
  1. configure_logging()   ← always first
  2. configure_tracing()   ← conditional on otlp_endpoint
  3. Database engines (nlp_db + intelligence_db)
  4. Valkey client + WatchlistCache
"""

from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING, Any

import structlog.contextvars
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from nlp_pipeline.api.routes import dlq, entities, health, internal_costs, search, signals
from nlp_pipeline.config import Settings
from nlp_pipeline.infrastructure.intelligence_db.session import (
    _build_intelligence_factories,
)
from nlp_pipeline.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
from nlp_pipeline.infrastructure.nlp_db.session import _build_nlp_factories
from observability import configure_logging, get_logger  # type: ignore[import-untyped]
from observability.metrics import add_prometheus_middleware, create_metrics  # type: ignore[import-untyped]
from observability.tracing import add_otel_middleware, configure_tracing  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

logger = get_logger("nlp_pipeline.app")  # type: ignore[no-any-return]

_VALID_REQUEST_ID_RE = re.compile(r"^[a-zA-Z0-9\-]{1,64}$")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Propagate X-Request-ID through the request lifecycle (STANDARDS.md §5)."""

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


async def _expire_stale_embeddings(
    session_factory: Any,
    config: Settings,
) -> None:
    """On startup, if current embedding model differs from stored, bulk-expire stale rows (PLAN-0031 B-2).

    Sets ``expires_at = now()`` on any ``chunk_embeddings`` / ``section_embeddings``
    rows whose ``model_id`` does not match ``config.embedding_model_id``.
    The EmbeddingRetryWorker will re-generate them on its next cycle.
    """
    import structlog
    from sqlalchemy import text

    _log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

    async with session_factory() as session:
        r1 = await session.execute(
            text("UPDATE chunk_embeddings SET expires_at = now() WHERE model_id != :current AND expires_at IS NULL"),
            {"current": config.embedding_model_id},
        )
        r2 = await session.execute(
            text("UPDATE section_embeddings SET expires_at = now() WHERE model_id != :current AND expires_at IS NULL"),
            {"current": config.embedding_model_id},
        )
        if r1.rowcount > 0 or r2.rowcount > 0:
            _log.warning(
                "embedding_model_changed",
                stale_chunk_count=r1.rowcount,
                stale_section_count=r2.rowcount,
                current_model=config.embedding_model_id,
            )
        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan — sets up database and Valkey for API endpoints.

    Background processes (consumers, dispatcher) run as standalone entry points
    per R22.  This lifespan only initialises resources the API layer needs.
    """
    settings: Settings = app.state.settings

    # 1. Logging — always first
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )
    log = get_logger("nlp_pipeline.app")  # type: ignore[no-any-return]

    # 2. Tracing (conditional)
    if settings.otlp_endpoint:
        configure_tracing(
            service_name=settings.service_name,
            otlp_endpoint=settings.otlp_endpoint,
        )

    # 3. Start InternalJWTMiddleware — fetch JWKS from S9 at startup
    jwt_middleware: InternalJWTMiddleware | None = getattr(app.state, "_jwt_middleware", None)
    if jwt_middleware is not None:
        await jwt_middleware.startup()

    # 4. Database engines — R23 dual factory (write + read) for both DBs
    nlp_engine, nlp_read_engine, nlp_sf, nlp_read_sf = _build_nlp_factories(settings)
    intel_engine, intel_read_engine, intel_sf, intel_read_sf = _build_intelligence_factories(settings)
    app.state.nlp_engine = nlp_engine
    app.state.nlp_read_engine = nlp_read_engine
    app.state.intel_engine = intel_engine
    app.state.intel_read_engine = intel_read_engine
    app.state.nlp_session_factory = nlp_sf
    app.state.nlp_write_factory = nlp_sf
    app.state.nlp_read_factory = nlp_read_sf
    app.state.intelligence_session_factory = intel_sf
    app.state.intel_write_factory = intel_sf
    app.state.intel_read_factory = intel_read_sf

    # 4b. Expire stale embeddings if embedding model changed (PLAN-0031 B-2)
    try:
        await _expire_stale_embeddings(nlp_sf, settings)
    except Exception:
        log.warning("expire_stale_embeddings_failed", exc_info=True)

    # 5. Valkey + WatchlistCache
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]
    from nlp_pipeline.infrastructure.valkey.watchlist_cache import WatchlistCache

    valkey = create_valkey_client_from_url(settings.valkey_url)
    watchlist_cache = WatchlistCache(client=valkey._redis, key=settings.valkey_watchlist_key)  # type: ignore[attr-defined]
    app.state.valkey = valkey
    app.state.watchlist_cache = watchlist_cache

    # 5. Optional: MinIO chunk text store (for search use case text hydration)
    app.state.chunk_text_store = None
    if settings.storage_access_key:
        try:
            from nlp_pipeline.infrastructure.storage.chunk_text_store import MinIOChunkTextStore
            from storage.factory import build_object_storage  # type: ignore[import-untyped]
            from storage.settings import StorageSettings  # type: ignore[import-untyped]

            _obj_storage = build_object_storage(
                settings=StorageSettings(
                    endpoint=settings.storage_endpoint,
                    access_key=settings.storage_access_key,
                    secret_key=settings.storage_secret_key,
                ),
            )
            app.state.chunk_text_store = MinIOChunkTextStore(_obj_storage, settings.chunk_bucket)
            log.info("chunk_text_store_configured", bucket=settings.chunk_bucket)
        except Exception:
            log.warning("chunk_text_store_init_failed", exc_info=True)

    # 6. Optional: UnresolvedResolutionWorker (PLAN-0033 T-C-2-02)
    _unresolved_worker_task: asyncio.Task[None] | None = None
    if settings.unresolved_resolution_enabled:
        from nlp_pipeline.infrastructure.workers.unresolved_resolution_worker import (
            UnresolvedResolutionWorker,
        )

        # usage_logger requires a per-call session; pass None here and rely on
        # the worker's internal structlog for cost observability until a
        # session-factory-based adapter is wired (follow-up task).
        _unresolved_worker = UnresolvedResolutionWorker(
            nlp_session_factory=nlp_sf,
            settings=settings,
            intel_session_factory=intel_sf,
            usage_logger=None,
        )
        await _unresolved_worker.recover_stale_escalated()
        _unresolved_worker_task = asyncio.create_task(_unresolved_worker.run_loop())
        log.info("unresolved_resolution_worker_started")

    log.info("service_started", service=settings.service_name)
    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    if _unresolved_worker_task is not None:
        _unresolved_worker_task.cancel()
        with suppress(asyncio.CancelledError):
            await _unresolved_worker_task
    await valkey.close()
    await nlp_engine.dispose()
    if nlp_read_engine is not nlp_engine:
        await nlp_read_engine.dispose()
    await intel_engine.dispose()
    if intel_read_engine is not intel_engine:
        await intel_read_engine.dispose()
    log.info("service_stopped", service=settings.service_name)


def _register_exception_handlers(app: FastAPI) -> None:
    from nlp_pipeline.domain.errors import NLPDomainError

    @app.exception_handler(NLPDomainError)
    async def _domain_error(_request: Request, exc: NLPDomainError) -> JSONResponse:
        logger.warning("domain_error", error=str(exc))  # type: ignore[no-any-return]
        return JSONResponse(status_code=422, content={"error": "domain_error", "detail": str(exc)})

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", error=str(exc))  # type: ignore[no-any-return]
        return JSONResponse(status_code=500, content={"error": "internal_error"})


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the NLP Pipeline FastAPI application."""
    app = FastAPI(
        title="nlp-pipeline",
        version="2025.6.0",
        lifespan=lifespan,
    )
    settings = settings or Settings()
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

    # Middleware (must be registered before lifespan starts)
    app.add_middleware(RequestIdMiddleware)
    metrics = create_metrics(service_name=settings.service_name)
    add_prometheus_middleware(app, metrics)
    add_otel_middleware(app)
    app.state.metrics = metrics

    _register_exception_handlers(app)

    app.include_router(health.router, tags=["health"])
    app.include_router(signals.router)
    app.include_router(entities.router)
    app.include_router(search.router)
    app.include_router(dlq.router)
    app.include_router(internal_costs.router)

    return app
