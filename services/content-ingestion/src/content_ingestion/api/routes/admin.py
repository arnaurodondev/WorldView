"""Admin API endpoints for source management and pipeline control."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from content_ingestion.api.dependencies import AdminAuthDep, UoWDep
from content_ingestion.api.schemas import (
    SourceCreateRequest,
    SourceListResponse,
    SourceResponse,
    SourceStatusDetail,
    SourceUpdateRequest,
    StatusResponse,
    TriggerResponse,
)
from content_ingestion.application.use_cases.create_source import CreateSourceUseCase
from content_ingestion.application.use_cases.list_sources import ListSourcesUseCase
from content_ingestion.application.use_cases.pipeline_status import GetPipelineStatusUseCase
from content_ingestion.application.use_cases.trigger_source import TriggerSourceUseCase
from content_ingestion.application.use_cases.update_source import UpdateSourceUseCase

router = APIRouter(prefix="/api/v1", tags=["admin"])


@router.get("/sources", response_model=SourceListResponse)
async def list_sources(
    _auth: AdminAuthDep,
    uow: UoWDep,
) -> SourceListResponse:
    """List all configured polling sources."""
    uc = ListSourcesUseCase(uow)
    items = await uc.execute()
    return SourceListResponse(
        sources=[
            SourceResponse(
                id=item.id,
                name=item.name,
                source_type=item.source_type,
                enabled=item.enabled,
                last_fetch_at=item.last_fetch_at,
            )
            for item in items
        ]
    )


@router.post("/sources", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(
    body: SourceCreateRequest,
    _auth: AdminAuthDep,
    uow: UoWDep,
) -> SourceResponse:
    """Create a new polling source.

    The scheduler process will automatically pick up new enabled sources
    on its next tick — no hot-add needed (R22).
    """
    uc = CreateSourceUseCase(uow)
    result = await uc.execute(
        name=body.name,
        source_type=body.source_type,
        config=body.config,
        enabled=body.enabled,
    )
    return SourceResponse(
        id=result.id,
        name=result.name,
        source_type=result.source_type,
        enabled=result.enabled,
    )


@router.put("/sources/{source_id}", response_model=SourceResponse)
async def update_source(
    source_id: UUID,
    body: SourceUpdateRequest,
    _auth: AdminAuthDep,
    uow: UoWDep,
) -> SourceResponse:
    """Update an existing polling source.

    Enabling/disabling a source takes effect on the next scheduler tick (R22).
    """
    uc = UpdateSourceUseCase(uow)
    updates = body.model_dump(exclude_unset=True)
    result = await uc.execute(source_id, **updates)
    if result is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return SourceResponse(
        id=result.id,
        name=result.name,
        source_type=result.source_type,
        enabled=result.enabled,
    )


@router.post("/sources/{source_id}/trigger", response_model=TriggerResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_source(
    source_id: UUID,
    _auth: AdminAuthDep,
    uow: UoWDep,
) -> TriggerResponse:
    """Trigger an immediate fetch cycle for a source.

    Creates a task row that a worker will pick up — no fire-and-forget (R22).
    """
    uc = TriggerSourceUseCase(uow)
    result = await uc.execute(source_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return TriggerResponse(source_id=result.source_id, task_id=result.task_id)


@router.get("/status", response_model=StatusResponse)
async def pipeline_status(
    _auth: AdminAuthDep,
    uow: UoWDep,
) -> StatusResponse:
    """Pipeline ingestion status summary."""
    uc = GetPipelineStatusUseCase(uow)
    result = await uc.execute()
    return StatusResponse(
        sources=[
            SourceStatusDetail(
                name=s.name,
                last_fetch_at=s.last_fetch_at,
                articles_fetched_24h=s.articles_fetched_24h,
                errors_24h=s.errors_24h,
            )
            for s in result.sources
        ],
        outbox_pending=result.outbox_pending,
        dlq_count=result.dlq_count,
    )
