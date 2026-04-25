"""FastAPI route handlers for market-ingestion service.

API surface:
  POST /api/v1/ingest/trigger        — Trigger ingestion for symbols
  POST /api/v1/ingest/backfill       — Backfill historical data
  GET  /api/v1/ingest/status         — Task status counts
  GET  /api/v1/policies              — List enabled polling policies
  GET  /api/v1/eodhd/quota/status    — EODHD quota + daily budget (admin)
  GET  /healthz                      — Liveness probe (always 200)
  GET  /readyz                       — Readiness probe (checks DB + storage)
  GET  /metrics                      — Prometheus metrics endpoint
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import prometheus_client
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from market_ingestion.api.dependencies import (
    get_object_store,
    get_read_uow,
    get_settings,
    get_uow,
)
from market_ingestion.api.schemas import (
    BackfillRequest,
    BackfillResponse,
    CircuitBreakerDetail,
    DailyBudgetDetail,
    EodhdQuotaStatusResponse,
    HealthResponse,
    PolicyListResponse,
    PolicySummary,
    ReadyResponse,
    TaskStatusResponse,
    TriggerRequest,
    TriggerResponse,
)
from market_ingestion.application.use_cases.backfill import BackfillUseCase
from market_ingestion.application.use_cases.daily_budget_tracker import DailyBudgetTracker
from market_ingestion.application.use_cases.snapshot_quota import SnapshotEodhdQuotaUseCase
from market_ingestion.application.use_cases.trigger_ingestion import TriggerIngestionUseCase
from market_ingestion.domain.enums import DatasetType, Provider
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from market_ingestion.application.ports.adapters import ObjectStoreAdapter
    from market_ingestion.application.ports.unit_of_work import ReadOnlyUnitOfWork, UnitOfWork
    from market_ingestion.config import Settings

logger = get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Liveness probe
# ---------------------------------------------------------------------------


@router.get("/healthz", response_model=HealthResponse, tags=["probes"])
async def healthz() -> HealthResponse:
    """Liveness probe — always returns 200 OK."""
    return HealthResponse(status="ok")


# ---------------------------------------------------------------------------
# Readiness probe
# ---------------------------------------------------------------------------


@router.get("/readyz", response_model=ReadyResponse, tags=["probes"])
async def readyz(
    request: Request,
    settings: Settings = Depends(get_settings),
    uow: ReadOnlyUnitOfWork = Depends(get_read_uow),  # R27: read-only check
    object_store: ObjectStoreAdapter = Depends(get_object_store),
) -> ReadyResponse:
    """Readiness probe — checks DB connectivity and storage availability."""
    checks: dict[str, str] = {}
    all_ok = True

    # F-003B: JWKS public key must be loaded before accepting traffic.
    if getattr(request.app.state, "_internal_jwt_public_key", None) is None:
        checks["jwks"] = "not_loaded"
        all_ok = False
    else:
        checks["jwks"] = "ok"

    # DB check — run a trivial query
    try:
        await uow.tasks.count_by_status()
        checks["db"] = "ok"
    except Exception as exc:
        logger.error("readyz_db_check_failed", error_type=type(exc).__name__, error=str(exc))
        checks["db"] = "error"
        all_ok = False

    # Storage check — verify the ingestion bucket is reachable
    try:
        await object_store.exists(settings.storage_bucket, "__healthcheck__")
        checks["storage"] = "ok"
    except Exception as exc:
        logger.error("readyz_storage_check_failed", error_type=type(exc).__name__, error=str(exc))
        checks["storage"] = "error"
        all_ok = False

    status_str = "ok" if all_ok else "degraded"
    if not all_ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ReadyResponse(status=status_str, checks=checks).model_dump(),
        )
    return ReadyResponse(status=status_str, checks=checks)


# ---------------------------------------------------------------------------
# Ingest routes
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/ingest/trigger",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TriggerResponse,
    tags=["ingestion"],
)
async def trigger_ingestion(
    req: TriggerRequest,
    uow: UnitOfWork = Depends(get_uow),
) -> TriggerResponse:
    """Trigger immediate ingestion for one or more symbols."""
    try:
        provider = Provider(req.provider)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown provider: {req.provider!r}",
        ) from exc

    try:
        dataset_type = DatasetType(req.dataset_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown dataset_type: {req.dataset_type!r}",
        ) from exc

    use_case = TriggerIngestionUseCase(uow=uow)
    result = await use_case.execute(
        provider=provider,
        symbols=req.symbols,
        dataset_type=dataset_type,
        timeframe=req.timeframe,
        exchange=req.exchange,
    )
    return TriggerResponse(
        tasks_created=result.tasks_created,
        tasks_skipped=result.tasks_skipped,
        symbols=req.symbols,
    )


@router.post(
    "/api/v1/ingest/backfill",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=BackfillResponse,
    tags=["ingestion"],
)
async def trigger_backfill(
    req: BackfillRequest,
    uow: UnitOfWork = Depends(get_uow),
) -> BackfillResponse:
    """Trigger a historical backfill for a single symbol."""
    try:
        provider = Provider(req.provider)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown provider: {req.provider!r}",
        ) from exc

    use_case = BackfillUseCase(uow=uow)
    start_dt = datetime(req.start_date.year, req.start_date.month, req.start_date.day, tzinfo=UTC)
    end_dt = datetime(req.end_date.year, req.end_date.month, req.end_date.day, tzinfo=UTC)

    try:
        result = await use_case.execute(
            provider=provider,
            symbol=req.symbol,
            start_date=start_dt,
            end_date=end_dt,
            timeframe=req.timeframe,
            chunk_days=req.chunk_days,
            exchange=req.exchange,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return BackfillResponse(
        tasks_created=result.tasks_created,
        tasks_skipped=result.tasks_skipped,
        chunks=result.chunks,
        symbol=req.symbol,
    )


@router.get(
    "/api/v1/ingest/status",
    response_model=TaskStatusResponse,
    tags=["ingestion"],
)
async def ingest_status(
    uow: ReadOnlyUnitOfWork = Depends(get_read_uow),  # R27: read-only query
) -> TaskStatusResponse:
    """Return task counts grouped by status."""
    counts = await uow.tasks.count_by_status()
    return TaskStatusResponse(counts=counts, total=sum(counts.values()))


# ---------------------------------------------------------------------------
# Policy routes
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/policies",
    response_model=PolicyListResponse,
    tags=["policies"],
)
async def list_policies(
    uow: ReadOnlyUnitOfWork = Depends(get_read_uow),  # R27: read-only query
) -> PolicyListResponse:
    """List all enabled polling policies."""
    policies = await uow.policies.list_enabled()
    summaries = [
        PolicySummary(
            id=p.id,
            provider=p.provider.value,
            dataset_type=p.dataset_type.value,
            symbol=p.symbol,
            timeframe=p.timeframe,
            base_interval_seconds=p.base_interval_seconds,
            is_enabled=p.is_enabled,
            priority=p.priority,
        )
        for p in policies
    ]
    return PolicyListResponse(policies=summaries, total=len(summaries))


# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------


@router.get("/metrics", tags=["probes"])
async def metrics() -> Response:
    """Prometheus metrics — protected by InternalJWTMiddleware (PRD-0025)."""
    data = prometheus_client.generate_latest()
    return Response(content=data, media_type=prometheus_client.CONTENT_TYPE_LATEST)


# ---------------------------------------------------------------------------
# EODHD quota admin (W3-8) — READ-ONLY (with get_or_create fallback)
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/eodhd/quota/status",
    response_model=EodhdQuotaStatusResponse,
    tags=["admin"],
)
async def eodhd_quota_status(
    uow: UnitOfWork = Depends(get_uow),
) -> EodhdQuotaStatusResponse:
    """Return the current EODHD quota and daily budget status.

    This is a read-heavy endpoint — it uses the write UoW because both
    SnapshotEodhdQuotaUseCase and DailyBudgetTracker call ``get_or_create``
    on ProviderBudget, which writes the default row on first run.

    Response fields:
    * ``credits_used`` / ``monthly_budget``: token-bucket proxy for monthly quota.
    * ``daily_budget``: DailyBudgetTracker with 0.85 safety factor.
    * ``circuit_breaker``: stubbed "closed" / 0 trips until CB is wired.
    """
    # Snapshot the raw quota data from the DB.
    quota_uc = SnapshotEodhdQuotaUseCase(uow=uow)
    snapshot = await quota_uc.execute()

    # Compute the daily budget status using the same UoW.
    # Each use case opens its own `async with uow:` context; the UoW is
    # reusable across multiple sequential executions.
    budget_tracker = DailyBudgetTracker(uow=uow, safety_factor=0.85)
    daily_status = await budget_tracker.get_status()

    return EodhdQuotaStatusResponse(
        provider=snapshot.provider,
        month=snapshot.month_year,
        credits_used=snapshot.credits_used,
        monthly_budget=snapshot.budget_limit,
        # Round to one decimal place for display; avoid 0-division (budget_limit=0).
        utilization_pct=round(snapshot.utilization_ratio * 100, 1),
        daily_budget=DailyBudgetDetail(
            allotted=daily_status.allotted,
            spent=daily_status.spent,
            headroom_ratio=round(daily_status.headroom_ratio, 4),
        ),
        # Circuit breaker not yet wired; stub as "closed" with 0 trips.
        circuit_breaker=CircuitBreakerDetail(
            state="closed",
            trips_today=0,
        ),
    )
