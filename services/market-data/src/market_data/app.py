"""FastAPI application factory with full infrastructure wiring."""

from __future__ import annotations

import asyncio
import contextlib
import re
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import prometheus_client
import structlog.contextvars
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from market_data.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
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

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]


_VALID_REQUEST_ID_RE = re.compile(r"^[a-zA-Z0-9\-]{1,64}$")

# Refresh screen field metadata in Valkey every 6 hours (PRD-0017 §6.2).
_SCREEN_FIELDS_REFRESH_INTERVAL_SECONDS = 6 * 3600


def _get_static_screen_fields() -> list:
    """Return the 25 static ScreenFieldMetadata instances (PRD-0017 §6.5, Wave L-1/L-2/L-5c)."""
    from market_data.domain.entities import ScreenFieldMetadata

    return [
        ScreenFieldMetadata(
            name="pe_ratio",
            label="P/E Ratio",
            field_type="numeric",
            unit="x",
            description="Trailing P/E (TTM)",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        ScreenFieldMetadata(
            name="revenue_usd",
            label="Revenue",
            field_type="numeric",
            unit="USD M",
            description="Annual revenue (USD millions)",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        ScreenFieldMetadata(
            name="gross_margin_pct",
            label="Gross Margin",
            field_type="numeric",
            unit="%",
            description="Gross profit / revenue x 100",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        ScreenFieldMetadata(
            name="net_margin_pct",
            label="Net Margin",
            field_type="numeric",
            unit="%",
            description="Net income / revenue x 100",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        ScreenFieldMetadata(
            name="ev_ebitda",
            label="EV/EBITDA",
            field_type="numeric",
            unit="x",
            description="Enterprise value / EBITDA",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        ScreenFieldMetadata(
            name="debt_to_equity",
            label="Debt/Equity",
            field_type="numeric",
            unit="x",
            description="Total debt / shareholders equity",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        ScreenFieldMetadata(
            name="return_on_equity",
            label="ROE",
            field_type="numeric",
            unit="%",
            description="Net income / avg. equity x 100",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        ScreenFieldMetadata(
            name="dividend_yield_pct",
            label="Dividend Yield",
            field_type="numeric",
            unit="%",
            description="Annual dividends / price x 100",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        ScreenFieldMetadata(
            name="market_cap_usd",
            label="Market Cap",
            field_type="numeric",
            unit="USD M",
            description="Market capitalisation (USD millions)",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        ScreenFieldMetadata(
            name="price_to_book",
            label="Price/Book",
            field_type="numeric",
            unit="x",
            description="Market price / book value per share",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        ScreenFieldMetadata(
            name="operating_margin_pct",
            label="Operating Margin",
            field_type="numeric",
            unit="%",
            description="Operating income / revenue x 100",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        ScreenFieldMetadata(
            name="current_ratio",
            label="Current Ratio",
            field_type="numeric",
            unit="x",
            description="Current assets / current liabilities",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        # ── Wave L-1: instrument-attribute filters ────────────────────────────
        ScreenFieldMetadata(
            name="country",
            label="Country",
            field_type="text",
            unit=None,
            description="ISO 3-letter country code (e.g. USA, GBR)",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        ScreenFieldMetadata(
            name="exchange",
            label="Exchange",
            field_type="text",
            unit=None,
            description="Exchange code (e.g. NASDAQ, NYSE, LSE)",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        # PLAN-0098 W3 BP-585: booleans stored as 0/1 numeric for constraint compatibility
        # (ck_screen_field_metadata_field_type CHECK admits only 'numeric'/'text').
        ScreenFieldMetadata(
            name="has_fundamentals",
            label="Has Fundamentals",
            field_type="numeric",
            unit=None,
            description="Instrument has at least one fundamentals data point",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        # PLAN-0098 W3 BP-585: booleans stored as 0/1 numeric for constraint compatibility
        # (ck_screen_field_metadata_field_type CHECK admits only 'numeric'/'text').
        ScreenFieldMetadata(
            name="has_ohlcv",
            label="Has OHLCV",
            field_type="numeric",
            unit=None,
            description="Instrument has at least one OHLCV bar",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        # ── Wave L-2: snapshot display metrics ────────────────────────────────
        ScreenFieldMetadata(
            name="eps_ttm",
            label="EPS (TTM)",
            field_type="numeric",
            unit="USD",
            description="Earnings per share — trailing twelve months",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        ScreenFieldMetadata(
            name="avg_volume_30d",
            label="Avg Volume 30d",
            field_type="numeric",
            unit="shares",
            description="Average daily trading volume over the past 30 days",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        ScreenFieldMetadata(
            name="free_cash_flow",
            label="Free Cash Flow",
            field_type="numeric",
            unit="USD",
            description="Operating cash flow minus capital expenditures",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        ScreenFieldMetadata(
            name="fcf_margin",
            label="FCF Margin",
            field_type="numeric",
            unit="%",
            description="Free cash flow as a percentage of revenue",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        ScreenFieldMetadata(
            name="interest_coverage",
            label="Interest Coverage",
            field_type="numeric",
            unit="x",
            description="EBIT divided by interest expense",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        ScreenFieldMetadata(
            name="net_debt_to_ebitda",
            label="Net Debt/EBITDA",
            field_type="numeric",
            unit="x",
            description="(Total debt - cash) / EBITDA; negative = net cash position",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        ScreenFieldMetadata(
            name="credit_rating",
            label="Credit Rating",
            field_type="text",
            unit=None,
            description="S&P / EODHD credit rating string (e.g. AA+, BBB-)",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        # ── Wave L-4a: analyst / ownership / short snapshot fields ────────────
        # MUST stay in lock-step with the seed inserts in migration
        # ``025_seed_l4a_analyst_ownership_fields.py`` — the 6-hour refresh
        # loop UPSERTs from this list and would otherwise overwrite the
        # migration's seeded values with divergent labels/descriptions.
        ScreenFieldMetadata(
            name="analyst_target_price",
            label="ANALYST TGT",
            field_type="numeric",
            unit="USD",
            description="Analyst consensus 12-month target price (USD)",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        ScreenFieldMetadata(
            name="analyst_consensus_rating",
            label="CONSENSUS",
            field_type="numeric",
            unit="1-5",
            description="Analyst consensus rating on a 1-5 scale (higher = more bullish)",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        ScreenFieldMetadata(
            name="institutional_ownership_pct",
            label="INST OWN%",
            field_type="numeric",
            unit="%",
            description="Institutional ownership as a decimal fraction of shares outstanding",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        ScreenFieldMetadata(
            name="short_percent",
            label="SHORT %",
            field_type="numeric",
            unit="%",
            description="Short interest as a decimal fraction of float",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        # ── Wave L-5c: calendar (date) snapshot fields ────────────────────────
        # LOCK-STEP with migration 028 ``_L5C_FIELDS`` — divergence would let
        # the 6-hour refresh loop overwrite the migration's seeded rows on the
        # next tick. ``field_type='numeric'`` because the
        # ``ck_screen_field_metadata_field_type`` CHECK admits only
        # ('numeric', 'text') and the UI filter is a number-of-days input
        # (``next_earnings_within_days``).
        ScreenFieldMetadata(
            name="next_earnings_date",
            label="NEXT EARN",
            field_type="numeric",
            unit="date",
            description="Next scheduled earnings report date (filter accepts days-from-today)",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
        ScreenFieldMetadata(
            name="next_dividend_date",
            label="NEXT DIV",
            field_type="numeric",
            unit="date",
            description="Next scheduled dividend payment date (filter accepts days-from-today)",
            observed_min=None,
            observed_max=None,
            null_fraction=0.0,
        ),
    ]


async def _do_screen_fields_refresh(
    write_factory: async_sessionmaker,
    valkey_client: ValkeyClient,
    log: object,
) -> None:
    """Upsert 12 static field definitions to DB and warm Valkey cache (PRD-0017 §6.2)."""
    from common.time import utc_now  # type: ignore[import-untyped]
    from market_data.infrastructure.cache.screen_fields_cache import ScreenFieldsCache
    from market_data.infrastructure.db.repositories.screen_field_metadata_repo import (
        PgScreenFieldMetadataRepository,
    )

    fields = _get_static_screen_fields()
    now = utc_now()

    async with write_factory() as session:
        repo = PgScreenFieldMetadataRepository(session)
        await repo.upsert_batch(fields, now)
        await session.commit()

    cache = ScreenFieldsCache(valkey_client)
    await cache.set_all(fields)

    log.info("screen_fields_refreshed", field_count=len(fields))  # type: ignore[attr-defined]


_SCREEN_FIELDS_REFRESH_RETRY_SECONDS = 60  # Back-off on first-run / transient failure


async def _screen_fields_refresh_loop(
    write_factory: async_sessionmaker,
    valkey_client: ValkeyClient,
    log: object,
) -> None:
    """Background task: seed + refresh screen field metadata every 6 hours.

    Sleeps ``_SCREEN_FIELDS_REFRESH_INTERVAL_SECONDS`` (6 h) after a successful
    refresh.  On failure, backs off ``_SCREEN_FIELDS_REFRESH_RETRY_SECONDS`` (60 s)
    so the initial warm-up is not delayed by 6 h if the DB or Valkey is momentarily
    unavailable at startup.
    """
    while True:
        try:
            await _do_screen_fields_refresh(write_factory, valkey_client, log)
            await asyncio.sleep(_SCREEN_FIELDS_REFRESH_INTERVAL_SECONDS)
        except Exception as exc:
            log.error("screen_fields_refresh_error", error=str(exc))  # type: ignore[attr-defined]
            await asyncio.sleep(_SCREEN_FIELDS_REFRESH_RETRY_SECONDS)


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
    """Async context manager that starts and stops all service infrastructure."""
    from market_data.infrastructure.db.session import build_read_engine, build_session_factory, build_write_engine

    settings = app.state.settings

    # 1. Logging — always first
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )
    log = get_logger("market_data.app")

    # 1b. Boot-time security guard (PLAN-0093 Wave A-1 / F-LOG-JWT-001).
    # Refuses to start when JWT verification is disabled AND APP_ENV is unset.
    assert_app_env_or_die(
        service_name=settings.service_name,
        internal_jwt_skip_verification=settings.internal_jwt_skip_verification,
    )

    # 2. Internal JWT middleware startup — fetch JWKS from S9 (PRD-0025)
    jwt_middleware = InternalJWTMiddleware(
        app,
        jwks_url=f"{settings.api_gateway_url}/internal/jwks",
        skip_verification=settings.internal_jwt_skip_verification,
        service_name=settings.service_name,
        jti_replay_check_enabled=settings.internal_jwt_jti_check_enabled,
    )
    await jwt_middleware.startup()

    # 2. Tracing (optional — middleware already registered in create_app)
    if settings.otlp_endpoint:
        configure_tracing(service_name=settings.service_name, otlp_endpoint=settings.otlp_endpoint)

    # 2b. Sentry — fourth observability pillar (default-off: SENTRY_ENABLED=false)
    init_sentry(service_name=settings.service_name, settings=SentrySettings())

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

    from market_data.infrastructure.cache.price_snapshot_cache import PriceSnapshotCache
    from market_data.infrastructure.cache.quote_cache import QuoteCache
    from market_data.infrastructure.cache.screen_fields_cache import ScreenFieldsCache

    app.state.quote_cache = QuoteCache(valkey_client)
    app.state.screen_fields_cache = ScreenFieldsCache(valkey_client)
    # PriceSnapshotCache: 2-hour TTL cache for resolved price snapshots (W1-6)
    app.state.price_snapshot_cache = PriceSnapshotCache(valkey_client)

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
            access_key=settings.storage_access_key.get_secret_value(),
            secret_key=settings.storage_secret_key.get_secret_value(),
        )
        object_storage = build_object_storage(storage_settings)
    except Exception:
        log.warning("object_storage_init_failed_degrading")
    app.state.object_storage = object_storage

    # 7. EODHD HTTP client (on-demand profile enrichment, PLAN-0073 Worker 13J)
    from market_data.infrastructure.eodhd.client import EodhHdClient

    app.state.eodhd_client = EodhHdClient(
        api_key=settings.eodhd_api_key.get_secret_value(),
        base_url=settings.eodhd_base_url,
    )

    # 8. Background task: seed screen field metadata to DB + Valkey, then refresh every 6h
    # R22 exemption: screen fields cache-warmer is explicitly exempted from the
    # "no asyncio.create_task in lifespan" rule per PRD-0017 §6.2.
    refresh_task = asyncio.create_task(_screen_fields_refresh_loop(write_factory, valkey_client, log))

    log.info("service_started", service=settings.service_name)
    yield

    refresh_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await refresh_task

    eodhd_client = getattr(app.state, "eodhd_client", None)
    if eodhd_client is not None:
        await eodhd_client.aclose()

    await valkey_client.close()
    await write_engine.dispose()
    if read_engine is not write_engine:
        await read_engine.dispose()

    log.info("service_stopped", service=settings.service_name)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    from market_data.config import Settings

    settings = Settings()  # type: ignore[call-arg]

    app = FastAPI(
        title="market-data",
        version="2025.6.0",
        lifespan=lifespan,
    )
    app.state.settings = settings

    # Exception handlers — must be registered before middleware so that handler
    # responses are still processed by middleware layers (e.g. Prometheus timing).
    register_error_handlers(app)

    # Middleware — must be registered before app starts (Starlette requirement)
    app.add_middleware(
        InternalJWTMiddleware,
        jwks_url=f"{settings.api_gateway_url}/internal/jwks",
        skip_verification=settings.internal_jwt_skip_verification,
        service_name=settings.service_name,
        jti_replay_check_enabled=settings.internal_jwt_jti_check_enabled,
    )
    app.add_middleware(RequestIdMiddleware)
    metrics = create_metrics(service_name=settings.service_name)
    add_prometheus_middleware(app, metrics)
    add_otel_middleware(app)
    app.state.metrics = metrics

    # Health probes (no auth, no lifespan dependency)
    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> dict[str, object]:
        from fastapi import HTTPException
        from sqlalchemy import text

        _log = get_logger("market_data.app")
        checks: dict[str, str] = {}
        all_ok = True

        # F-003B: JWKS public key must be loaded before accepting traffic.
        # Exception (dev/test): when InternalJWTMiddleware is in
        # skip_verification mode the public key is intentionally absent — the
        # middleware sets ``app.state._internal_jwt_skip_verification = True``
        # so readyz can distinguish "intentionally absent" from "failed to
        # fetch". Matches portfolio/app.py:222.
        skip_jwt = getattr(app.state, "_internal_jwt_skip_verification", False)
        if skip_jwt:
            checks["jwks"] = "skipped"
        elif getattr(app.state, "_internal_jwt_public_key", None) is None:
            checks["jwks"] = "not_loaded"
            all_ok = False
        else:
            checks["jwks"] = "ok"

        # DB check
        try:
            sf = getattr(app.state, "session_factory", None)
            if sf is not None:
                async with sf() as session:
                    await session.execute(text("SELECT 1"))
                checks["db"] = "ok"
            else:
                checks["db"] = "not_ready"
                all_ok = False
        except Exception as exc:
            _log.error("readyz_db_check_failed", error_type=type(exc).__name__, error=str(exc))
            checks["db"] = "error"
            all_ok = False

        # Valkey check
        try:
            valkey = getattr(app.state, "valkey_client", None)
            if valkey is not None:
                ok = await valkey.ping()
                checks["valkey"] = "ok" if ok else "error"
                if not ok:
                    all_ok = False
            else:
                checks["valkey"] = "not_ready"
                all_ok = False
        except Exception as exc:
            _log.error("readyz_valkey_check_failed", error_type=type(exc).__name__, error=str(exc))
            checks["valkey"] = "error"
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
            _log.error("readyz_storage_check_failed", error_type=type(exc).__name__, error=str(exc))
            checks["storage"] = "error"
            all_ok = False

        if not all_ok:
            raise HTTPException(
                status_code=503,
                detail={"status": "degraded", "checks": checks},
            )
        return {"status": "ok", "checks": checks}

    @app.get("/metrics")
    async def metrics_endpoint() -> Response:
        """Prometheus metrics — protected by InternalJWTMiddleware (PRD-0025)."""
        data = prometheus_client.generate_latest()
        return Response(content=data, media_type=prometheus_client.CONTENT_TYPE_LATEST)

    # Register API routers
    from market_data.api.routers import (
        fundamental_metrics,
        fundamentals,
        instruments,
        internal_instruments,
        market,
        ohlcv,
        peers,
        prediction_markets,
        price_snapshot,
        quotes,
        securities,
    )

    app.include_router(instruments.router, prefix="/api/v1")
    app.include_router(market.router, prefix="/api/v1")
    app.include_router(ohlcv.router, prefix="/api/v1")
    app.include_router(quotes.router, prefix="/api/v1")
    # fundamental_metrics MUST be registered before fundamentals to avoid
    # /fundamentals/timeseries being matched by /fundamentals/{security_id}
    app.include_router(fundamental_metrics.router, prefix="/api/v1")
    app.include_router(fundamentals.router, prefix="/api/v1")
    app.include_router(securities.router, prefix="/api/v1")
    # peers: /instruments/{id}/peers — registered after instruments.router to
    # keep the literal /peers sub-path distinct from the UUID catch-all.
    # W5-T-S2-01: top-N market-cap peers in same GICS industry.
    app.include_router(peers.router, prefix="/api/v1")
    # prediction_markets: /prediction-markets/{market_id}/history registered
    # before /{market_id} inside the router to avoid path-param conflicts
    app.include_router(prediction_markets.router, prefix="/api/v1")
    # price_snapshot: internal endpoints — only S9 (api-gateway) calls these
    # via the internal JWT mechanism (PRD-0025)
    app.include_router(price_snapshot.router, prefix="/internal/v1")
    # PLAN-0100 T-W5-01: top-N-by-market-cap internal endpoint consumed by
    # market-ingestion's FundamentalsRefreshWorker. Same /internal/v1 prefix
    # + same JWT-required guard as the other system-to-system routes.
    app.include_router(internal_instruments.router, prefix="/internal/v1")

    return app
