"""FastAPI application factory — NLP Pipeline service (S6).

Lifespan sequence (STANDARDS.md §5):
  1. configure_logging()   ← always first
  2. configure_tracing()   ← conditional on otlp_endpoint
  3. Database engines (nlp_db + intelligence_db)
  4. Valkey client + WatchlistCache
  5. ML clients (NER, Embedding, Extraction)
  6. BackpressureController
  7. ArticleProcessingConsumer + WatchlistEventConsumer (background tasks)
  8. NLPPipelineOutboxDispatcher (background task)
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

from nlp_pipeline.api.routes import dlq, health, signals
from nlp_pipeline.config import Settings
from nlp_pipeline.infrastructure.backpressure.controller import BackpressureController
from nlp_pipeline.infrastructure.intelligence_db.session import (
    create_intelligence_session_factory,
)
from nlp_pipeline.infrastructure.metrics.prometheus import s6_ollama_queue_depth_current
from nlp_pipeline.infrastructure.nlp_db.session import create_session_factory
from nlp_pipeline.infrastructure.outbox.dispatcher import NLPPipelineOutboxDispatcher
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


async def _supervised_dispatcher(dispatcher: NLPPipelineOutboxDispatcher, app: FastAPI) -> None:
    """Restart the outbox dispatcher on crash with exponential backoff."""
    failures = 0
    while True:
        try:
            await dispatcher.run()
            break
        except asyncio.CancelledError:
            raise
        except Exception:
            failures += 1
            delay = min(5 * (2**failures), 300)
            logger.exception(  # type: ignore[no-any-return]
                "dispatcher_crashed",
                restart_delay=delay,
                failures=failures,
            )
            app.state.dispatcher_healthy = False
            await asyncio.sleep(delay)
            app.state.dispatcher_healthy = True


async def _metrics_poller(bp: BackpressureController, interval: float = 5.0) -> None:
    """Periodically update the Ollama queue depth gauge."""
    while True:
        with contextlib.suppress(Exception):
            s6_ollama_queue_depth_current.set(bp.gauge_value())
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
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

    # 3. Database engines
    nlp_engine, nlp_sf = create_session_factory(settings.database_url)
    intel_engine, intel_sf = create_intelligence_session_factory(settings.intelligence_database_url)
    app.state.nlp_engine = nlp_engine
    app.state.intel_engine = intel_engine
    app.state.nlp_session_factory = nlp_sf
    app.state.intelligence_session_factory = intel_sf

    # 4. Valkey + WatchlistCache
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]
    from nlp_pipeline.infrastructure.valkey.watchlist_cache import WatchlistCache

    valkey = create_valkey_client_from_url(settings.valkey_url)
    # WatchlistCache expects the raw asyncio Redis client (valkey._redis)
    watchlist_cache = WatchlistCache(client=valkey._redis, key=settings.valkey_watchlist_key)  # type: ignore[attr-defined]
    app.state.valkey = valkey
    app.state.watchlist_cache = watchlist_cache

    # 5. ML clients
    import asyncio as _asyncio

    from ml_clients.adapters.gliner_local import GLiNERLocalAdapter  # type: ignore[import-not-found]
    from ml_clients.adapters.ollama_embedding import (
        OllamaEmbeddingAdapter,  # type: ignore[import-not-found]
    )
    from ml_clients.adapters.ollama_extraction import (
        OllamaExtractionAdapter,  # type: ignore[import-not-found]
    )

    _ml_sem = _asyncio.Semaphore(settings.embedding_max_concurrent)
    ner_client = GLiNERLocalAdapter(model_path=settings.ner_model_id, semaphore=_asyncio.Semaphore(1))
    embedding_client = OllamaEmbeddingAdapter(
        base_url=settings.ollama_base_url,
        model_id=settings.embedding_model_id,
        semaphore=_ml_sem,
    )
    extraction_client = OllamaExtractionAdapter(
        base_url=settings.ollama_base_url,
        model_id=settings.extraction_model_id,
        semaphore=_ml_sem,
    )
    app.state.ner_client = ner_client
    app.state.embedding_client = embedding_client
    app.state.extraction_client = extraction_client

    # 6. Backpressure controller
    bp = BackpressureController(
        max_depth=settings.max_ollama_queue_depth,
        resume_depth=settings.resume_ollama_queue_depth,
    )
    app.state.backpressure = bp

    # 7. Outbox dispatcher (supervised background task)
    dispatcher = NLPPipelineOutboxDispatcher(settings=settings, session_factory=nlp_sf)
    app.state.dispatcher = dispatcher
    app.state.dispatcher_healthy = True
    dispatch_task: asyncio.Task[Any] = asyncio.create_task(_supervised_dispatcher(dispatcher, app))

    # 8. Consumers (background tasks)
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from nlp_pipeline.infrastructure.consumer.article_consumer import (
        ArticleProcessingConsumer,
    )
    from nlp_pipeline.infrastructure.consumer.watchlist_consumer import (
        WatchlistEventConsumer,
    )

    article_config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_consumer_group,
        topics=[settings.topic_article_stored],
    )
    article_consumer = ArticleProcessingConsumer(
        config=article_config,
        settings=settings,
        nlp_session_factory=nlp_sf,
        intelligence_session_factory=intel_sf,
        storage=None,  # MinIO storage injected below if configured
        watchlist_cache=watchlist_cache,
        ner_client=ner_client,
        embedding_client=embedding_client,
        extraction_client=extraction_client,
        backpressure=bp,
    )

    watchlist_config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_watchlist_consumer_group,
        topics=[settings.topic_watchlist_updated],
    )
    watchlist_consumer = WatchlistEventConsumer(
        config=watchlist_config,
        watchlist_cache=watchlist_cache,
    )

    # Optional: configure MinIO storage for article text download
    try:
        from storage.factory import build_object_storage  # type: ignore[import-untyped]
        from storage.settings import StorageSettings  # type: ignore[import-untyped]

        storage_settings = StorageSettings(
            endpoint=settings.storage_endpoint,
            access_key=settings.storage_access_key,
            secret_key=settings.storage_secret_key,
        )
        storage = build_object_storage(settings=storage_settings)
        article_consumer._storage = storage  # type: ignore[attr-defined]
        app.state.storage = storage
    except Exception:
        log.warning("minio_not_configured_article_downloads_disabled", exc_info=True)

    # Start consumers and metrics poller as background tasks
    article_task: asyncio.Task[Any] = asyncio.create_task(article_consumer.run())
    watchlist_task: asyncio.Task[Any] = asyncio.create_task(watchlist_consumer.run())
    metrics_task: asyncio.Task[Any] = asyncio.create_task(_metrics_poller(bp))

    log.info("service_started", service=settings.service_name)
    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    article_consumer.stop()  # type: ignore[attr-defined]
    watchlist_consumer.stop()  # type: ignore[attr-defined]
    dispatcher.stop()

    for task in (article_task, watchlist_task, dispatch_task, metrics_task):
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    await valkey.close()
    await nlp_engine.dispose()
    await intel_engine.dispose()
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

    # Middleware (must be registered before lifespan starts)
    app.add_middleware(RequestIdMiddleware)
    metrics = create_metrics(service_name=settings.service_name)
    add_prometheus_middleware(app, metrics)
    add_otel_middleware(app)
    app.state.metrics = metrics

    _register_exception_handlers(app)

    app.include_router(health.router, tags=["health"])
    app.include_router(signals.router)
    app.include_router(dlq.router)

    return app
