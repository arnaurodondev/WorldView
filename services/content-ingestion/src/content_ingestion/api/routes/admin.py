"""Admin API endpoints for source management and pipeline control."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import common.time  # type: ignore[import-untyped]
from content_ingestion.api.dependencies import AdminAuthDep, DbSessionDep
from content_ingestion.api.schemas import (
    SourceCreateRequest,
    SourceListResponse,
    SourceResponse,
    SourceStatusDetail,
    SourceUpdateRequest,
    StatusResponse,
    TriggerResponse,
)
from content_ingestion.domain.entities import ContentIngestionTask, Source, SourceType
from content_ingestion.infrastructure.db.models import (
    DeadLetterQueueModel,
    FetchLogModel,
    OutboxEventModel,
    SourceAdapterStateModel,
    SourceModel,
)
from content_ingestion.infrastructure.db.repositories.source import SourceRepository
from content_ingestion.infrastructure.db.repositories.task import TaskRepository

router = APIRouter(prefix="/api/v1", tags=["admin"])


def _source_to_response(source: SourceModel, last_fetch_at: object = None) -> SourceResponse:
    return SourceResponse(
        id=source.id,
        name=source.name,
        source_type=source.source_type,
        enabled=source.enabled,
        last_fetch_at=last_fetch_at,  # type: ignore[arg-type]
    )


@router.get("/sources", response_model=SourceListResponse)
async def list_sources(
    _auth: AdminAuthDep,
    session: DbSessionDep,
) -> SourceListResponse:
    """List all configured polling sources."""
    repo = SourceRepository(session)
    sources = await repo.get_all()

    # Join adapter state for last_run_at
    state_result = await session.execute(select(SourceAdapterStateModel))
    state_map = {s.source_id: s for s in state_result.scalars().all()}

    items = []
    for src in sources:
        state = state_map.get(src.id)
        items.append(_source_to_response(src, last_fetch_at=state.last_run_at if state else None))
    return SourceListResponse(sources=items)


@router.post("/sources", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(
    body: SourceCreateRequest,
    _auth: AdminAuthDep,
    session: DbSessionDep,
) -> SourceResponse:
    """Create a new polling source.

    The scheduler process will automatically pick up new enabled sources
    on its next tick — no hot-add needed (R22).
    """
    repo = SourceRepository(session)
    source = await repo.create(
        name=body.name,
        source_type=body.source_type,
        config=body.config,
        enabled=body.enabled,
    )
    await session.commit()
    return _source_to_response(source)


@router.put("/sources/{source_id}", response_model=SourceResponse)
async def update_source(
    source_id: UUID,
    body: SourceUpdateRequest,
    _auth: AdminAuthDep,
    session: DbSessionDep,
) -> SourceResponse:
    """Update an existing polling source.

    Enabling/disabling a source takes effect on the next scheduler tick (R22).
    """
    repo = SourceRepository(session)
    existing = await repo.get_by_id(source_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Source not found")

    updates = body.model_dump(exclude_unset=True)
    if updates:
        source = await repo.update(source_id, **updates)
    else:
        source = existing
    await session.commit()
    return _source_to_response(source)


@router.post("/sources/{source_id}/trigger", response_model=TriggerResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_source(
    source_id: UUID,
    _auth: AdminAuthDep,
    session: DbSessionDep,
) -> TriggerResponse:
    """Trigger an immediate fetch cycle for a source.

    Creates a task row that a worker will pick up — no fire-and-forget (R22).
    """
    repo = SourceRepository(session)
    source_model = await repo.get_by_id(source_id)
    if source_model is None:
        raise HTTPException(status_code=404, detail="Source not found")

    # Create domain source and build a task
    source = Source(
        id=source_model.id,
        name=source_model.name,
        source_type=SourceType(source_model.source_type),
        enabled=source_model.enabled,
        config=source_model.config,
        created_at=source_model.created_at,
    )
    task = ContentIngestionTask.create_for_source(source, window_start=common.time.utc_now())

    task_repo = TaskRepository(session)
    await task_repo.add(task)
    await session.commit()

    return TriggerResponse(source_id=source_id, task_id=task.id)


@router.get("/status", response_model=StatusResponse)
async def pipeline_status(
    _auth: AdminAuthDep,
    session: DbSessionDep,
) -> StatusResponse:
    """Pipeline ingestion status summary."""
    return await _build_status(session)


async def _build_status(session: AsyncSession) -> StatusResponse:
    """Query DB for per-source stats, outbox pending, and DLQ count."""
    import datetime as dt

    import common.time as ct

    cutoff = ct.utc_now() - dt.timedelta(hours=24)

    # Per-source stats
    sources_result = await session.execute(select(SourceModel))
    sources = list(sources_result.scalars().all())

    state_result = await session.execute(select(SourceAdapterStateModel))
    state_map = {s.source_id: s for s in state_result.scalars().all()}

    details: list[SourceStatusDetail] = []
    for src in sources:
        state = state_map.get(src.id)
        # Count fetched in last 24h
        fetched_count_result = await session.execute(
            select(func.count())
            .select_from(FetchLogModel)
            .where(FetchLogModel.source_id == src.id, FetchLogModel.fetched_at >= cutoff)
        )
        fetched_24h = fetched_count_result.scalar() or 0

        details.append(
            SourceStatusDetail(
                name=src.name,
                last_fetch_at=state.last_run_at if state else None,
                articles_fetched_24h=fetched_24h,
                errors_24h=state.error_count if state else 0,
            )
        )

    # Outbox pending count
    outbox_result = await session.execute(
        select(func.count()).select_from(OutboxEventModel).where(OutboxEventModel.status == "pending")
    )
    outbox_pending = outbox_result.scalar() or 0

    # DLQ count
    dlq_result = await session.execute(
        select(func.count()).select_from(DeadLetterQueueModel).where(DeadLetterQueueModel.status == "failed")
    )
    dlq_count = dlq_result.scalar() or 0

    return StatusResponse(sources=details, outbox_pending=outbox_pending, dlq_count=dlq_count)
