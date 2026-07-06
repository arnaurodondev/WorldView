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

from nlp_pipeline.api.routes import (
    admin,
    dlq,
    embed,
    entities,
    health,
    internal_costs,
    internal_news_rollup,
    news,
    search,
    signals,
    trending_entities,
)
from nlp_pipeline.api.routes.search_documents import router as search_documents_router
from nlp_pipeline.config import Settings
from nlp_pipeline.infrastructure.intelligence_db.session import (
    _build_intelligence_factories,
)
from nlp_pipeline.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
from nlp_pipeline.infrastructure.nlp_db.session import _build_nlp_factories
from observability import configure_logging, get_logger, register_error_handlers  # type: ignore[import-untyped]
from observability.metrics import (  # type: ignore[import-untyped]
    add_prometheus_middleware,
    create_metrics,
    create_ml_metrics,
)
from observability.sentry import SentrySettings, init_sentry  # type: ignore[import-untyped]
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


# The two embedding tables this housekeeping drains. Hardcoded literals (never
# user input), so interpolating them into the SQL below is injection-safe.
_EMBEDDING_TABLES: tuple[str, ...] = ("chunk_embeddings", "section_embeddings")


async def _drain_stale_embeddings_for_table(
    session_factory: Any,
    table: str,
    current_ids: list[str],
    config: Settings,
) -> int:
    """Expire stale rows in *table* in bounded, per-batch-committed UPDATEs.

    Bounds the write set (and therefore its HNSW graph churn) to
    ``config.embedding_expiry_batch_size`` rows per statement, each in its own
    transaction with a ``SET LOCAL statement_timeout`` so a large one-time expiry
    after a genuine model change can never trip the 60 s OLTP backstop. Loops
    until a batch expires fewer than ``batch_size`` rows (drained) or the per-run
    cap is hit. Returns the total rows expired.

    Injection safety: *table* is one of the hardcoded :data:`_EMBEDDING_TABLES`
    literals; ``current_ids`` and the batch size are BOUND parameters; the
    ``SET LOCAL`` timeout is an ``int`` coerced from config.
    """
    from sqlalchemy import text

    batch_size = max(1, config.embedding_expiry_batch_size)
    timeout_ms = config.embedding_expiry_statement_timeout_ms
    max_batches = max(1, config.embedding_expiry_max_batches_per_run)

    # NOT IN (:m0, :m1, ...) over the current-label set — all bound params.
    placeholders = ", ".join(f":m{i}" for i in range(len(current_ids)))
    id_params: dict[str, Any] = {f"m{i}": mid for i, mid in enumerate(current_ids)}
    # Bound the UPDATE to a batch of primary keys (ORDER-free LIMIT is fine — we
    # loop to drain everything) so the churned index pages stay small per commit.
    update_sql = text(
        f"UPDATE {table} SET expires_at = now() "  # noqa: S608 - table is a hardcoded literal; ids/batch are bound
        f"WHERE embedding_id IN ("
        f"  SELECT embedding_id FROM {table} "
        f"  WHERE model_id NOT IN ({placeholders}) AND expires_at IS NULL "
        f"  LIMIT :batch"
        f")"
    )

    total = 0
    for _ in range(max_batches):
        async with session_factory() as session:
            if timeout_ms and timeout_ms > 0:
                # SET LOCAL cannot bind params; timeout_ms is coerced to int.
                await session.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
            result = await session.execute(update_sql, {**id_params, "batch": batch_size})
            await session.commit()
        rowcount = result.rowcount or 0
        total += rowcount
        if rowcount < batch_size:
            break  # fewer than a full batch left → drained
    return total


async def _expire_stale_embeddings(
    session_factory: Any,
    config: Settings,
) -> None:
    """On startup, expire embeddings written by a NO-LONGER-current model (PRE-1 / PLAN-0031 B-2).

    Sets ``expires_at = now()`` on ``chunk_embeddings`` / ``section_embeddings``
    rows whose ``model_id`` is not one of ``current_embedding_model_ids(config)``
    (the logical AND provider-API labels of the configured model), so the
    EmbeddingRetryWorker regenerates them on its next cycle.

    Root cause of PRE-1: the old query compared only against
    ``config.embedding_model_id`` (``"bge-large"``), but the live DeepInfra
    provider writes ``config.embedding_api_model_id``
    (``"BAAI/bge-large-en-v1.5"``) — the SAME physical model under a different
    label — so ~half the corpus was flagged stale and the unbounded UPDATE
    (~13k rows, each an HNSW re-insert) blew the 10-min statement_timeout on
    every boot. Comparing against BOTH labels makes the common case a 0-row
    no-op; the drain is batched so a genuine model change still completes without
    tripping the timeout. Idempotent — safe to run every boot.
    """
    import structlog

    from nlp_pipeline.bootstrap.embedding import current_embedding_model_ids

    _log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

    current_ids = current_embedding_model_ids(config)
    if not current_ids:
        # No configured model labels → we cannot classify staleness; skip rather
        # than expire the ENTIRE corpus on a misconfiguration.
        _log.warning("expire_stale_embeddings_skipped_no_model_id")
        return

    stale_counts: dict[str, int] = {}
    for table in _EMBEDDING_TABLES:
        stale_counts[table] = await _drain_stale_embeddings_for_table(session_factory, table, current_ids, config)

    if any(stale_counts.values()):
        _log.warning(
            "embedding_model_changed",
            stale_chunk_count=stale_counts["chunk_embeddings"],
            stale_section_count=stale_counts["section_embeddings"],
            current_models=current_ids,
        )


async def _run_expire_stale_embeddings(
    session_factory: Any,
    config: Settings,
    log: Any,
) -> None:
    """Background wrapper: run the drain and log (never raise) on failure.

    Exceptions in a fire-and-forget ``asyncio.create_task`` are otherwise
    swallowed, so we catch and log here — mirroring the previous inline
    ``try/except`` — while re-raising ``CancelledError`` so shutdown can await it.
    """
    try:
        await _expire_stale_embeddings(session_factory, config)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.warning("expire_stale_embeddings_failed", exc_info=True)


def _build_embedding_client(settings: Settings) -> object:
    """Instantiate the embedding adapter for the API process.

    Thin shim over :func:`nlp_pipeline.bootstrap.embedding.build_embedding_client`
    — the implementation moved there so the API process and the standalone
    embedding-retry worker share one source of truth (PLAN-0057 QA A-004).
    """
    from nlp_pipeline.bootstrap.embedding import build_embedding_client

    return build_embedding_client(settings)


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

    # 2b. Sentry — fourth observability pillar (default-off: SENTRY_ENABLED=false)
    init_sentry(service_name=settings.service_name, settings=SentrySettings())

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

    # 4b. Expire stale embeddings if the embedding model changed (PRE-1 / PLAN-0031 B-2).
    # Run OFF the boot critical path as a background task: a genuine model change
    # can leave tens of thousands of stale rows and each expiry forces an HNSW
    # re-insert, so a synchronous drain would block startup (and the old unbounded
    # UPDATE tripped the boot statement_timeout — PRE-1). The task drains in
    # bounded, committed batches and is cancelled on shutdown. Common case (model
    # unchanged) finishes in milliseconds.
    app.state._expire_embeddings_task = asyncio.create_task(_run_expire_stale_embeddings(nlp_sf, settings, log))

    # 5. Valkey + WatchlistCache
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]
    from nlp_pipeline.infrastructure.valkey.watchlist_cache import WatchlistCache

    valkey = create_valkey_client_from_url(settings.valkey_url)
    watchlist_cache = WatchlistCache(client=valkey._redis, key=settings.valkey_watchlist_key)  # type: ignore[attr-defined]
    app.state.valkey = valkey
    app.state.watchlist_cache = watchlist_cache

    # 5b. Embedding client for POST /api/v1/embed — provider-selectable.
    # The API process runs separately from article_consumer_main; it needs its own
    # embedding client instance so the embed endpoint is not tied to Ollama.
    app.state.embedding_client = _build_embedding_client(settings)
    log.info(
        "api_embedding_client_ready",
        provider=settings.embedding_provider,
    )

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

    log.info("service_started", service=settings.service_name)
    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    # Cancel the background stale-embedding drain BEFORE disposing the engine it
    # uses, so an in-flight batch can't run against a torn-down pool.
    expire_task: asyncio.Task[None] | None = getattr(app.state, "_expire_embeddings_task", None)
    if expire_task is not None and not expire_task.done():
        expire_task.cancel()
        with suppress(asyncio.CancelledError):
            await expire_task
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
    settings = settings or Settings()  # type: ignore[call-arg]
    app.state.settings = settings

    # Exception handlers — must be registered before middleware so that handler
    # responses are still processed by middleware layers (e.g. Prometheus timing).
    register_error_handlers(app)

    # InternalJWTMiddleware (RS256 verifier — PRD-0025 Wave D)
    # We store the instance on app.state so lifespan can call startup() on it.
    jwks_url = f"{settings.api_gateway_url}/internal/jwks"
    jwt_middleware = InternalJWTMiddleware(
        app,
        jwks_url=jwks_url,
        skip_verification=settings.internal_jwt_skip_verification,
        service_name=settings.service_name,
        # S6 is internal-only: S8 forwards the same JWT multiple times per request.
        # JTI replay check is done at the S8 user-facing boundary; disabling here
        # prevents false 401s on the second S6 call (embed then chunk search).
        jti_replay_check_enabled=settings.jti_replay_check_enabled,
    )
    app.state._jwt_middleware = jwt_middleware
    app.add_middleware(
        InternalJWTMiddleware,
        jwks_url=jwks_url,
        skip_verification=settings.internal_jwt_skip_verification,
        service_name=settings.service_name,
        jti_replay_check_enabled=settings.jti_replay_check_enabled,
    )

    # Middleware (must be registered before lifespan starts)
    app.add_middleware(RequestIdMiddleware)
    metrics = create_metrics(service_name=settings.service_name)
    ml_metrics = create_ml_metrics(settings.service_name)
    add_prometheus_middleware(app, metrics)
    add_otel_middleware(app)
    app.state.metrics = metrics
    app.state.ml_metrics = ml_metrics

    _register_exception_handlers(app)

    app.include_router(health.router, tags=["health"])
    app.include_router(embed.router)
    app.include_router(signals.router)
    app.include_router(entities.router)
    app.include_router(search.router)
    app.include_router(news.router)
    app.include_router(trending_entities.router)
    app.include_router(dlq.router)
    app.include_router(internal_costs.router)
    # PLAN-0089 L-5a — 7-day news rollup endpoint consumed by market-data's
    # nightly SyncIntelligenceRollupUseCase (L-5b). Previously this router was
    # implemented but never registered, causing the S6NewsRollupClient to 404
    # on every call and leaving news_count_7d / llm_relevance_7d_max /
    # display_relevance_7d_weighted columns NULL across all 664 instruments.
    app.include_router(internal_news_rollup.router)
    # PLAN-0055 C-4: admin LLM replay endpoint.
    app.include_router(admin.router)
    # PLAN-0064 W6: full-text document search (stub in Wave 1, wired in Wave 3).
    app.include_router(search_documents_router)

    return app
