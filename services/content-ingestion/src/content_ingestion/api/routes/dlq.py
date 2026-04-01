"""DLQ admin endpoints — list, inspect, retry, resolve."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from content_ingestion.api.dependencies import AdminAuthDep, ReadUoWDep, UoWDep
from content_ingestion.api.schemas import DLQEntryResponse, DLQListResponse, DLQResolveRequest
from content_ingestion.application.use_cases.dlq_list import GetDLQEntryUseCase, ListDLQEntriesUseCase
from content_ingestion.application.use_cases.dlq_resolve import ResolveDLQEntryUseCase
from content_ingestion.application.use_cases.dlq_retry import RetryDLQEntryUseCase

router = APIRouter(prefix="/admin/dlq", tags=["dlq"])


@router.get("", response_model=DLQListResponse)
async def list_dlq(
    _auth: AdminAuthDep,
    uow: ReadUoWDep,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> DLQListResponse:
    """List open DLQ entries."""
    uc = ListDLQEntriesUseCase(uow)
    result = await uc.execute(limit=limit, offset=offset)
    return DLQListResponse(
        entries=[
            DLQEntryResponse(
                dlq_id=e.dlq_id,
                original_event_id=e.original_event_id,
                topic=e.topic,
                error_detail=e.error_detail,
                status=e.status,
                created_at=e.created_at,
                resolved_at=e.resolved_at,
                resolution_note=e.resolution_note,
            )
            for e in result.entries
        ],
        count=result.count,
    )


@router.get("/{dlq_id}", response_model=DLQEntryResponse)
async def get_dlq_entry(
    dlq_id: UUID,
    _auth: AdminAuthDep,
    uow: ReadUoWDep,
) -> DLQEntryResponse:
    """Get a single DLQ entry with full payload."""
    uc = GetDLQEntryUseCase(uow)
    entry = await uc.execute(dlq_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="DLQ entry not found")
    return DLQEntryResponse(
        dlq_id=entry.dlq_id,
        original_event_id=entry.original_event_id,
        topic=entry.topic,
        error_detail=entry.error_detail,
        status=entry.status,
        created_at=entry.created_at,
        resolved_at=entry.resolved_at,
        resolution_note=entry.resolution_note,
    )


@router.post("/{dlq_id}/retry", status_code=202)
async def retry_dlq_entry(
    dlq_id: UUID,
    _auth: AdminAuthDep,
    uow: UoWDep,
) -> dict[str, str]:
    """Requeue a DLQ entry back into the outbox."""
    uc = RetryDLQEntryUseCase(uow)
    result = await uc.execute(dlq_id)
    if result is None:
        raise HTTPException(status_code=404, detail="DLQ entry not found")
    return {"status": "requeued", "new_event_id": str(result.new_event_id)}


@router.post("/{dlq_id}/resolve", status_code=200)
async def resolve_dlq_entry(
    dlq_id: UUID,
    body: DLQResolveRequest,
    _auth: AdminAuthDep,
    uow: UoWDep,
) -> dict[str, str]:
    """Mark a DLQ entry as resolved with a note."""
    uc = ResolveDLQEntryUseCase(uow)
    found = await uc.execute(dlq_id, note=body.note)
    if not found:
        raise HTTPException(status_code=404, detail="DLQ entry not found")
    return {"status": "resolved"}
