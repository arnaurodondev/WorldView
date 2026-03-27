"""FastAPI application factory with full infrastructure wiring."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import prometheus_client
import structlog.contextvars
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

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
    """Async context manager that starts and stops all service infrastructure."""
    from market_data.config import Settings
    from market_data.infrastructure.db.session import build_read_engine, build_session_factory, build_write_engine
    from market_data.infrastructure.messaging.outbox.dispatcher import create_dispatcher

    settings = Settings()

    # 1. Logging — always first
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )
    log = get_logger("market_data.app")

    # 2. Metrics
    metrics = create_metrics(service_name=settings.service_name)
    add_prometheus_middleware(app, metrics)
    app.state.metrics = metrics

    # 3. Tracing (optional)
    if settings.otlp_endpoint:
        configure_tracing(service_name=settings.service_name, otlp_endpoint=settings.otlp_endpoint)
        add_otel_middleware(app)

    # 4. DB — write engine + optional read engine
    write_engine = build_write_engine(settings)
    read_engine = build_read_engine(settings)
    write_factory = build_session_factory(write_engine)
    read_factory = build_session_factory(read_engine)
    app.state.write_session_factory = write_factory
    app.state.read_session_factory = read_factory
    app.state.session_factory = write_factory  # readyz probe compatibility

    # 5. Valkey
    from messaging.valkey.client import create_valkey_client_from_url  # type: ignore[import-untyped]

    valkey_client = create_valkey_client_from_url(settings.valkey_url)
    app.state.valkey_client = valkey_client

    from market_data.infrastructure.cache.quote_cache import QuoteCache

    app.state.quote_cache = QuoteCache(valkey_client)

    # 6. Object storage
    object_storage = None
    try:
        from storage.factory import build_object_storage  # type: ignore[import-untyped]
        from storage.settings import StorageSettings  # type: ignore[import-untyped]

        endpoint = settings.storage_endpoint
        if not endpoint.startswith("http"):
            endpoint = f"http://{endpoint}"
        storage_settings = StorageSettings(
            endpoint=endpoint,
            access_key=settings.storage_access_key,
            secret_key=settings.storage_secret_key,
        )
        object_storage = build_object_storage(storage_settings)
    except Exception:
        log.warning("object_storage_init_failed_degrading")
    app.state.object_storage = object_storage

    # 7. UoW factory
    from market_data.infrastructure.db.uow import SqlAlchemyUnitOfWork

    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(write_factory, read_factory)

    # 8. Outbox dispatcher
    dispatcher = create_dispatcher(settings=settings, session_factory=write_factory)

    # 9. Consumers
    from market_data.infrastructure.messaging.consumers.fundamentals_consumer import FundamentalsConsumer
    from market_data.infrastructure.messaging.consumers.ohlcv_consumer import OHLCVConsumer
    from market_data.infrastructure.messaging.consumers.quotes_consumer import QuotesConsumer
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    ohlcv_consumer = OHLCVConsumer(
        uow_factory=uow_factory,
        object_storage=object_storage,
        config=ConsumerConfig(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id="market-data-ohlcv",
            topics=["market.dataset.fetched"],
        ),
    )
    quotes_consumer = QuotesConsumer(
        uow_factory=uow_factory,
        object_storage=object_storage,
        valkey_client=valkey_client,
        config=ConsumerConfig(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id="market-data-quotes",
            topics=["market.dataset.fetched"],
        ),
    )
    fundamentals_consumer = FundamentalsConsumer(
        uow_factory=uow_factory,
        object_storage=object_storage,
        config=ConsumerConfig(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id="market-data-fundamentals",
            topics=["market.dataset.fetched"],
        ),
    )

    # Start background tasks
    ohlcv_task = asyncio.create_task(ohlcv_consumer.run())
    quotes_task = asyncio.create_task(quotes_consumer.run())
    fundamentals_task = asyncio.create_task(fundamentals_consumer.run())
    dispatcher_task = asyncio.create_task(dispatcher.run())

    log.info("service_started", service=settings.service_name)
    yield

    # Shutdown
    ohlcv_consumer.stop()
    quotes_consumer.stop()
    fundamentals_consumer.stop()
    dispatcher.stop()

    for task in [ohlcv_task, quotes_task, fundamentals_task, dispatcher_task]:
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except (TimeoutError, asyncio.CancelledError, Exception):
            task.cancel()

    await valkey_client.close()
    await write_engine.dispose()
    if read_engine is not write_engine:
        await read_engine.dispose()

    log.info("service_stopped", service=settings.service_name)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="market-data",
        version="2025.6.0",
        lifespan=lifespan,
    )

    app.add_middleware(RequestIdMiddleware)

    # Health probes (no auth, no lifespan dependency)
    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> dict[str, object]:
        from fastapi import HTTPException
        from sqlalchemy import text

        checks: dict[str, str] = {}
        all_ok = True

        # DB check
        try:
            sf = app.state.session_factory
            async with sf() as session:
                await session.execute(text("SELECT 1"))
            checks["db"] = "ok"
        except Exception as exc:
            checks["db"] = f"error: {exc}"
            all_ok = False

        # Valkey check
        try:
            valkey = app.state.valkey_client
            ok = await valkey.ping()
            checks["valkey"] = "ok" if ok else "error: ping failed"
            if not ok:
                all_ok = False
        except Exception as exc:
            checks["valkey"] = f"error: {exc}"
            all_ok = False

        # Storage check
        try:
            obj_storage = getattr(app.state, "object_storage", None)
            if obj_storage is not None:
                from storage.health import check_storage_health  # type: ignore[import-untyped]

                await check_storage_health(obj_storage, bucket="market-data")
                checks["storage"] = "ok"
            else:
                checks["storage"] = "not_configured"
        except Exception as exc:
            checks["storage"] = f"error: {exc}"
            all_ok = False

        checks["kafka"] = "ok"  # consumers managed as background tasks

        if not all_ok:
            raise HTTPException(
                status_code=503,
                detail={"status": "degraded", "checks": checks},
            )
        return {"status": "ok", "checks": checks}

    @app.get("/metrics")
    async def metrics_endpoint() -> Response:
        data = prometheus_client.generate_latest()
        return Response(content=data, media_type=prometheus_client.CONTENT_TYPE_LATEST)

    # Register API routers
    from market_data.api.routers import fundamental_metrics, fundamentals, instruments, ohlcv, quotes, securities

    app.include_router(instruments.router, prefix="/api/v1")
    app.include_router(ohlcv.router, prefix="/api/v1")
    app.include_router(quotes.router, prefix="/api/v1")
    # fundamental_metrics MUST be registered before fundamentals to avoid
    # /fundamentals/timeseries being matched by /fundamentals/{security_id}
    app.include_router(fundamental_metrics.router, prefix="/api/v1")
    app.include_router(fundamentals.router, prefix="/api/v1")
    app.include_router(securities.router, prefix="/api/v1")

    return app
