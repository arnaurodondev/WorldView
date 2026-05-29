"""FastAPI application factory — knowledge-graph service (S7).

Lifespan wiring (PLAN-0003 / STANDARDS.md §5 canonical pattern):
  1. configure_logging()                  — always first
  2. create_metrics() + middleware        — Prometheus
  3. configure_tracing() (optional)       — OTel if otlp_endpoint set
  4. intelligence_db session factories   — read/write + read-only

Background processes run as standalone entry points (R22 / PLAN-0011 Wave C-3):
  - knowledge_graph.infrastructure.messaging.outbox.dispatcher_main
  - knowledge_graph.infrastructure.scheduler.scheduler_main
  - knowledge_graph.infrastructure.messaging.consumers.enriched_consumer_main
  - knowledge_graph.infrastructure.messaging.consumers.entity_consumer_main
  - knowledge_graph.infrastructure.messaging.consumers.fundamentals_consumer_main
  - knowledge_graph.infrastructure.messaging.consumers.instrument_consumer_main
  - knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer_main
  - knowledge_graph.infrastructure.messaging.consumers.economic_events_dataset_consumer_main
  - knowledge_graph.infrastructure.messaging.consumers.macro_indicator_dataset_consumer_main
  - knowledge_graph.infrastructure.messaging.consumers.insider_transactions_dataset_consumer_main
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import structlog.contextvars
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

import common.ids  # type: ignore[import-untyped]
from knowledge_graph.api import (
    claims,
    cypher,
    dlq,
    entities,
    entity_refresh,  # REQ-003 / TASK-W0-06: manual entity refresh trigger
    events,
    health,
    internal_costs,
    internal_intelligence_rollup,  # PLAN-0089 Wave L-5a: screener sync rollup
    internal_sectors,  # PLAN-0102 W2 T-W2-02: batch sector lookup for rag-chat briefs
    narratives,  # PRD-0074 Wave D: narrative history + manual trigger
    paths,  # PLAN-0074 Wave E2: path insights API
    routes,
    search,
    temporal_events,
)
from knowledge_graph.config import Settings
from knowledge_graph.domain.errors import KnowledgeGraphError
from knowledge_graph.infrastructure.intelligence_db.session import (
    _build_factories as _build_intel_factories,
)
from knowledge_graph.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
from observability import (  # type: ignore[import-untyped]
    assert_app_env_or_die,
    configure_logging,
    get_logger,
    register_error_handlers,
)
from observability.metrics import (  # type: ignore[import-untyped]
    add_prometheus_middleware,
    create_metrics,
    create_ml_metrics,
)
from observability.sentry import SentrySettings, init_sentry  # type: ignore[import-untyped]
from observability.tracing import add_otel_middleware, configure_tracing  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

_VALID_REQUEST_ID_RE = re.compile(r"^[a-zA-Z0-9\-]{1,64}$")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Propagate X-Request-ID through the request lifecycle."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
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

    # 1. Logging — always first (STANDARDS.md §5)
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )
    log = get_logger("knowledge_graph.app")

    # 1b. Boot-time security guard (PLAN-0093 Wave A-1 / F-LOG-JWT-001).
    # Refuses to start when JWT verification is disabled AND APP_ENV is unset.
    assert_app_env_or_die(
        service_name=settings.service_name,
        internal_jwt_skip_verification=settings.internal_jwt_skip_verification,
    )

    # 2. Tracing (conditional — middleware registered in create_app)
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

    # 4. intelligence_db session factories — R23 dual factory (write + read)
    engine, read_engine, write_factory, read_factory = _build_intel_factories(settings)
    app.state.session_factory = write_factory
    app.state.write_factory = write_factory
    app.state.read_factory = read_factory
    app.state.readonly_session_factory = read_factory
    app.state.engine = engine
    app.state.read_engine = read_engine

    # 4b. Register repo classes on app.state so the narratives.py POST route can resolve
    # them without importing from infrastructure/ (R25 compliance).
    # WHY app.state: the router never imports infrastructure directly; it reads these
    # class references from app.state at request time and passes them to the use case.
    from knowledge_graph.infrastructure.intelligence_db.repositories.narrative_repository import (
        NarrativeRepository as _NarrativeRepo,
    )
    from knowledge_graph.infrastructure.intelligence_db.repositories.outbox import (
        OutboxRepository as _OutboxRepo,
    )

    app.state.narrative_repo_class = _NarrativeRepo
    app.state.outbox_repo_class = _OutboxRepo

    # 4. Admin token (DLQ endpoint auth)
    app.state.admin_token = getattr(settings, "admin_token", "")

    # 5. Repair missing entity_embedding_state rows (PLAN-0057 Wave E-5 / F-MAJOR-06).
    # Idempotent: ensure_rows_exist uses ON CONFLICT DO NOTHING. Runs at every API
    # container start so any canonicals added by seeds or out-of-band scripts get
    # their definition / narrative / fundamentals rows before refresh workers tick.
    #
    # PLAN-0057 QA DS-004 fix: bound the await with a hard timeout (30 s) so a
    # slow intelligence_db (lock contention, pgvector hot loop, replica lag)
    # never blocks API readiness past the k8s readiness probe.  R22 forbids
    # ``asyncio.create_task`` here (TOPO-LIFESPAN) so we keep the call
    # synchronous-with-timeout instead of backgrounding it.  The repair is a
    # self-healing safety-net — InstrumentEntityConsumer +
    # InstrumentDiscoveredConsumer both call ensure_rows_exist on the live-write
    # path, so canonical state converges even if this run is skipped.
    import asyncio as _asyncio

    try:
        from knowledge_graph.infrastructure.workers.embedding_state_repair import (
            repair_missing_embedding_state,
        )

        repair_stats = await _asyncio.wait_for(
            repair_missing_embedding_state(write_factory),
            timeout=30.0,
        )
        log.info(
            "kg_embedding_state_repair_at_startup",
            canonicals_checked=repair_stats["checked"],
            rows_inserted=repair_stats["inserted"],
        )
    except TimeoutError:
        log.warning(
            "kg_embedding_state_repair_timeout",
            timeout_s=30.0,
            note="repair will retry next container restart; live-write path covers the gap",
        )
    except Exception as exc:  # pragma: no cover — never block startup on the repair
        log.warning("kg_embedding_state_repair_failed", error=str(exc))

    # 6. QW-1 — Warn if relation_type_registry has NULL embeddings.
    # NULL embeddings silently bypass S7 Block 11 Step 2 (ANN soft-map), causing
    # ~20-30% of valid relations to fall through to Step 3 (relation.type.proposed.v1)
    # instead of being written to the relations table.  Migration 0013 seeds embeddings
    # via Ollama; if Ollama was unavailable at migration time, all rows remain NULL.
    # Migration 0041 adds 5 new rows which also start with embedding = NULL.
    # This check is best-effort: any DB error is caught and logged, never raised.
    try:
        import sqlalchemy as _sa

        async with read_factory() as _session:
            _result = await _session.execute(
                _sa.text("SELECT COUNT(*) FROM relation_type_registry WHERE embedding IS NULL"),
            )
            _null_count: int = _result.scalar_one()
        if _null_count > 0:
            log.warning(
                "registry_embeddings_missing",
                null_count=_null_count,
                action=(
                    "re-run migration 0013 with Ollama running, or execute: "
                    "python -m knowledge_graph.infrastructure.scripts.seed_registry_embeddings"
                ),
                impact="S7 Block 11 Step 2 ANN soft-map bypassed for NULL-embedding rows",
            )
        else:
            log.info("registry_embeddings_ok", total_null=_null_count)
    except Exception as _exc:  # pragma: no cover — DB unavailable at startup is non-fatal
        log.warning("registry_embeddings_check_failed", error=str(_exc))

    try:
        log.info("knowledge_graph_started", service=settings.service_name)
        yield
    finally:
        await engine.dispose()
        if read_engine is not engine:
            await read_engine.dispose()
        log.info("knowledge_graph_stopped", service=settings.service_name)


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(KnowledgeGraphError)
    async def _domain_error(_request: Request, exc: KnowledgeGraphError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": "domain_error", "detail": str(exc)})

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        get_logger("knowledge_graph.app").exception("unhandled_error", error=str(exc))
        return JSONResponse(status_code=500, content={"error": "internal_error"})


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = settings or Settings()  # type: ignore[call-arg]

    app = FastAPI(
        title="knowledge-graph",
        version="2025.6.0",
        lifespan=lifespan,
    )
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
        # S7 is internal-only: S8 forwards the same JWT multiple times per request.
        # JTI replay check is done at the S8 user-facing boundary; disabling here
        # prevents false 401s when multiple graph lookups occur in one request.
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

    # Middleware (must be registered before app starts)
    app.add_middleware(RequestIdMiddleware)
    metrics = create_metrics(service_name=settings.service_name)
    ml_metrics = create_ml_metrics(settings.service_name)
    add_prometheus_middleware(app, metrics)
    add_otel_middleware(app)
    app.state.metrics = metrics
    app.state.ml_metrics = ml_metrics

    _register_exception_handlers(app)

    app.include_router(health.router, tags=["health"])
    app.include_router(routes.router)
    app.include_router(claims.router)
    app.include_router(entities.router)
    app.include_router(entities._internal_router)  # type: ignore[attr-defined]  # PRD-0074 Wave D internal intelligence route
    app.include_router(events.router)
    app.include_router(search.router)
    app.include_router(temporal_events.router)
    app.include_router(cypher.router)
    app.include_router(dlq.router)
    app.include_router(internal_costs.router)
    app.include_router(internal_intelligence_rollup.router)  # PLAN-0089 Wave L-5a
    app.include_router(internal_sectors.router)  # PLAN-0102 W2 T-W2-02
    app.include_router(paths.router)  # PLAN-0074 Wave E2 — path insights
    app.include_router(narratives.router)  # PRD-0074 Wave D — narrative history + manual trigger
    app.include_router(entity_refresh.router)  # REQ-003 / TASK-W0-06 — manual entity refresh trigger

    return app
