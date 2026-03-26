"""FastAPI application factory — content-ingestion service (S4)."""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import httpx
import structlog.contextvars
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from content_ingestion.api.routes import admin, dlq, health, internal
from content_ingestion.config import Settings
from content_ingestion.infrastructure.db.repositories.fetch_log import FetchLogRepository
from content_ingestion.infrastructure.db.repositories.outbox import OutboxRepository
from content_ingestion.infrastructure.db.session import create_session_factory
from content_ingestion.infrastructure.messaging.outbox.dispatcher import ContentIngestionOutboxDispatcher
from content_ingestion.infrastructure.metrics.prometheus import record_fetch, s4_dlq_total, s4_outbox_pending_total
from content_ingestion.infrastructure.scheduler.scheduler import ADAPTER_REGISTRY, IngestionScheduler
from content_ingestion.infrastructure.storage.minio_bronze import MinioBronzeAdapter
from messaging.pg.advisory_lock import pg_advisory_lock  # type: ignore[import-untyped]
from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]
from observability import configure_logging, get_logger  # type: ignore[import-untyped]
from observability.metrics import add_prometheus_middleware, create_metrics  # type: ignore[import-untyped]
from observability.tracing import add_otel_middleware, configure_tracing  # type: ignore[import-untyped]
from storage.factory import build_object_storage  # type: ignore[import-untyped]
from storage.settings import StorageSettings  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from content_ingestion.domain.entities import Source

logger_mod = get_logger("content_ingestion.app")  # type: ignore[no-any-return]


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


def _normalize_endpoint(endpoint: str) -> str:
    """Ensure MinIO endpoint has an explicit HTTP(S) scheme."""
    if endpoint.startswith("http://") or endpoint.startswith("https://"):
        return endpoint
    return f"http://{endpoint}"


async def _run_fetch_cycle(
    source: Source,
    settings: Settings,
    session_factory: object,
    storage: object,
    valkey: object,
    http_client: httpx.AsyncClient,
) -> None:
    """Execute one fetch-and-write cycle for a source.

    Lock is held only during writes, not during external API fetches.
    Watermarks from source_adapter_state drive incremental polling.
    """
    from content_ingestion.application.use_cases.fetch_and_write import FetchAndWriteUseCase
    from content_ingestion.domain.value_objects import TokenBucket
    from content_ingestion.infrastructure.adapters.eodhd.client import EODHDClient
    from content_ingestion.infrastructure.adapters.finnhub.client import FinnhubClient
    from content_ingestion.infrastructure.adapters.newsapi.client import NewsAPIClient
    from content_ingestion.infrastructure.adapters.sec_edgar.client import SECEdgarClient
    from content_ingestion.infrastructure.db.repositories.adapter_state import AdapterStateRepository

    adapter_cls = ADAPTER_REGISTRY.get(source.source_type)
    if adapter_cls is None:
        return

    import common.time as ct_mod

    # 1. Read watermark (outside lock — read-only)
    watermark_date = ""
    async with session_factory() as ro_session:  # type: ignore[operator]
        state_repo = AdapterStateRepository(ro_session)
        state = await state_repo.get(source.id)
        if state and state.last_watermark:
            watermark_date = state.last_watermark.strftime("%Y-%m-%d")

    # 2. Fetch articles from external API (outside lock — no DB writes)
    now = ct_mod.utc_now()
    rate_limiter = TokenBucket(capacity=10, tokens=10.0, refill_rate=10.0, last_refill=now)

    client: object
    if source.source_type.value == "eodhd":
        client = EODHDClient(http_client=http_client, api_key=settings.eodhd_api_key)  # type: ignore[arg-type]
    elif source.source_type.value == "sec_edgar":
        client = SECEdgarClient(http_client=http_client, user_agent=settings.sec_edgar_user_agent)  # type: ignore[arg-type]
    elif source.source_type.value == "finnhub":
        client = FinnhubClient(http_client=http_client, api_key=settings.finnhub_api_key)  # type: ignore[arg-type]
        rate_limiter = TokenBucket(capacity=55, tokens=55.0, refill_rate=55.0 / 60.0, last_refill=now)
    elif source.source_type.value == "newsapi":
        client = NewsAPIClient(
            http_client=http_client,  # type: ignore[arg-type]
            api_key=settings.newsapi_key,
            valkey=valkey,  # type: ignore[arg-type]
            daily_limit=settings.newsapi_daily_limit,
        )
    else:
        return

    # Build adapter — fetch happens outside lock
    fetch_log_dedup_session_cm = session_factory()  # type: ignore[operator]
    async with fetch_log_dedup_session_cm as dedup_session:
        dedup_repo = FetchLogRepository(dedup_session)

        if source.source_type.value == "newsapi":
            adapter = adapter_cls(  # type: ignore[call-arg]
                client=client,
                exists_fn=dedup_repo.exists_by_url_hash,
            )
        else:
            adapter = adapter_cls(  # type: ignore[call-arg]
                client=client,
                rate_limiter=rate_limiter,
                exists_fn=dedup_repo.exists_by_url_hash,
            )

        results = await adapter.fetch(source, is_backfill=settings.backfill_enabled, from_date=watermark_date)

    if not results:
        return

    # 3. Write results under advisory lock (lock only during writes)
    async with session_factory() as session, pg_advisory_lock(session, f"s4:fetch:{source.name}") as acquired:  # type: ignore[operator]
        if not acquired:
            return

        fetch_log_repo = FetchLogRepository(session)
        bronze = MinioBronzeAdapter(storage)  # type: ignore[arg-type]
        outbox_repo = OutboxRepository(session)
        use_case = FetchAndWriteUseCase(
            adapter=adapter,
            bronze=bronze,
            fetch_log_repo=fetch_log_repo,
            outbox_repo=outbox_repo,
            commit_fn=session.commit,
            rollback_fn=session.rollback,
        )

        summary = await use_case.execute(
            source,
            is_backfill=settings.backfill_enabled,
            from_date=watermark_date,
            prefetched_results=results,
        )

        # Update watermark after successful writes
        if summary.fetched > 0:
            adapter_state_repo = AdapterStateRepository(session)
            await adapter_state_repo.upsert(
                source.id,
                last_watermark=ct_mod.utc_now(),
                last_run_at=ct_mod.utc_now(),
            )
            await session.commit()

    # Record metrics
    record_fetch(
        source.name,
        fetched=summary.fetched,
        skipped=summary.skipped,
        failed=summary.failed,
        duration=summary.duration_seconds,
    )


async def _metrics_poller(session_factory: object, interval: int) -> None:
    """Periodically update outbox/DLQ gauge metrics."""
    from sqlalchemy import func, select

    from content_ingestion.infrastructure.db.models import DeadLetterQueueModel, OutboxEventModel

    while True:
        try:
            async with session_factory() as session:  # type: ignore[operator]
                outbox_result = await session.execute(
                    select(func.count()).select_from(OutboxEventModel).where(OutboxEventModel.status == "pending")
                )
                s4_outbox_pending_total.set(outbox_result.scalar() or 0)

                dlq_result = await session.execute(
                    select(func.count())
                    .select_from(DeadLetterQueueModel)
                    .where(DeadLetterQueueModel.status == "failed")
                )
                s4_dlq_total.set(dlq_result.scalar() or 0)
        except Exception:
            logger_mod.debug("metrics_poll_error", exc_info=True)
        await asyncio.sleep(interval)


async def _supervised_dispatcher(dispatcher: ContentIngestionOutboxDispatcher, app: FastAPI) -> None:
    """Supervisor loop that restarts the outbox dispatcher on crash with exponential backoff."""
    log = get_logger("content_ingestion.app")
    failures = 0
    while True:
        try:
            await dispatcher.run()
            break  # clean exit
        except asyncio.CancelledError:
            raise
        except Exception:
            failures += 1
            delay = min(5 * (2**failures), 300)
            log.exception("dispatcher_crashed", restart_delay=delay, consecutive_failures=failures)
            app.state.dispatcher_healthy = False
            await asyncio.sleep(delay)
            app.state.dispatcher_healthy = True


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings

    # 1. Logging — always first
    configure_logging(
        service_name="content-ingestion",
        level=settings.log_level,
        json=settings.log_json,
    )
    log = get_logger("content_ingestion.app")

    # 2. Metrics
    metrics = create_metrics(service_name="content-ingestion")
    add_prometheus_middleware(app, metrics)
    app.state.metrics = metrics

    # 3. Tracing (optional)
    if settings.otlp_endpoint:
        configure_tracing(
            service_name="content-ingestion",
            otlp_endpoint=settings.otlp_endpoint,
        )
        add_otel_middleware(app)

    # 4. Database — returns (engine, session_factory) so we can dispose engine on shutdown
    engine, session_factory = create_session_factory(settings)
    app.state.engine = engine
    app.state.session_factory = session_factory

    # 5. Valkey
    valkey = create_valkey_client_from_url(settings.valkey_url)
    app.state.valkey = valkey

    # 6. Object storage (bronze tier)
    storage_settings = StorageSettings(
        endpoint=_normalize_endpoint(settings.minio_endpoint),
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        use_ssl=settings.minio_secure,
        default_bucket=settings.minio_bucket,
    )
    storage = build_object_storage(settings=storage_settings)
    app.state.storage = storage

    # 7. HTTP client (shared across adapters)
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))
    app.state.http_client = http_client

    # 8. Outbox dispatcher (supervised background task)
    dispatcher = ContentIngestionOutboxDispatcher(
        settings=settings,
        session_factory=session_factory,
    )
    app.state.dispatcher = dispatcher
    app.state.dispatcher_healthy = True
    dispatch_task: asyncio.Task[Any] = asyncio.create_task(_supervised_dispatcher(dispatcher, app))

    # 9. Scheduler — fetch all sources and start polling
    async def run_fn(source: Source) -> None:
        await _run_fetch_cycle(source, settings, session_factory, storage, valkey, http_client)

    app.state.trigger_fn = run_fn

    from content_ingestion.infrastructure.db.repositories.source import SourceRepository

    scheduler = IngestionScheduler(
        interval_seconds=settings.scheduler_interval_seconds,
        run_fn=run_fn,
    )

    # Load sources from DB
    try:
        async with session_factory() as session:
            repo = SourceRepository(session)
            sources_models = await repo.get_all()

        from content_ingestion.domain.entities import Source as DomainSource
        from content_ingestion.domain.entities import SourceType

        domain_sources = [
            DomainSource(
                name=s.name,
                source_type=SourceType(s.source_type),
                enabled=s.enabled,
                config=s.config,
                id=s.id,
                created_at=s.created_at,
            )
            for s in sources_models
        ]
        await scheduler.start(domain_sources)
    except Exception:
        log.warning("scheduler_source_load_failed", exc_info=True)

    app.state.scheduler = scheduler

    # 10. Metrics poller (background task)
    metrics_task: asyncio.Task[None] = asyncio.create_task(
        _metrics_poller(session_factory, settings.outbox_metrics_poll_seconds)
    )

    log.info("service_started", service="content-ingestion")
    yield

    # Shutdown
    metrics_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await metrics_task

    await scheduler.stop()
    dispatcher.stop()
    dispatch_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await dispatch_task
    await http_client.aclose()
    await valkey.close()
    await engine.dispose()
    log.info("service_stopped", service="content-ingestion")


def _register_exception_handlers(app: FastAPI) -> None:
    """Map domain exceptions to appropriate HTTP status codes."""
    from content_ingestion.domain.exceptions import AdapterError, ConfigurationError, QuotaExhaustedError, StorageError

    @app.exception_handler(AdapterError)
    async def _adapter_error(_request: Request, exc: AdapterError) -> JSONResponse:
        logger_mod.error("adapter_error", error=str(exc))
        return JSONResponse(status_code=502, content={"error": "bad_gateway", "detail": "Upstream source error"})

    @app.exception_handler(QuotaExhaustedError)
    async def _quota_error(_request: Request, exc: QuotaExhaustedError) -> JSONResponse:
        logger_mod.warning("quota_exhausted", error=str(exc))
        return JSONResponse(status_code=429, content={"error": "too_many_requests", "detail": "Quota exhausted"})

    @app.exception_handler(ConfigurationError)
    async def _config_error(_request: Request, exc: ConfigurationError) -> JSONResponse:
        logger_mod.error("configuration_error", error=str(exc))
        return JSONResponse(status_code=500, content={"error": "internal_error", "detail": "Service misconfiguration"})

    @app.exception_handler(StorageError)
    async def _storage_error(_request: Request, exc: StorageError) -> JSONResponse:
        logger_mod.error("storage_error", error=str(exc))
        return JSONResponse(status_code=503, content={"error": "service_unavailable", "detail": "Storage unavailable"})

    @app.exception_handler(Exception)
    async def _unhandled_error(_request: Request, exc: Exception) -> JSONResponse:
        logger_mod.exception("unhandled_error", error=str(exc))
        return JSONResponse(status_code=500, content={"error": "internal_error"})


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        settings: Optional pre-built settings (for testing). Created automatically if None.
    """
    app = FastAPI(
        title="content-ingestion",
        version="2025.6.0",
        lifespan=lifespan,
    )
    app.state.settings = settings or Settings()
    app.add_middleware(RequestIdMiddleware)

    # Domain exception handlers
    _register_exception_handlers(app)

    app.include_router(health.router, tags=["health"])
    app.include_router(admin.router)
    app.include_router(dlq.router)
    app.include_router(internal.router)
    return app
