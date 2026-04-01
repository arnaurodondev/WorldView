"""DLQ admin endpoints — list, inspect, retry, resolve (X-Admin-Token required)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from nlp_pipeline.api.dependencies import AdminAuthDep, DLQUseCaseDep
from nlp_pipeline.api.schemas import DLQEntryResponse, DLQListResponse, DLQResolveRequest
from nlp_pipeline.application.ports.repositories import DLQEntryData

router = APIRouter(prefix="/admin/dlq", tags=["dlq"])


def _to_response(entry: DLQEntryData) -> DLQEntryResponse:
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


@router.get("", response_model=DLQListResponse)
async def list_dlq(
    _auth: AdminAuthDep,
    use_case: DLQUseCaseDep,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> DLQListResponse:
    """List open (unresolved) DLQ entries."""
    entries, total = await use_case.list_open(limit=limit, offset=offset)
    return DLQListResponse(entries=[_to_response(e) for e in entries], total=total)


@router.get("/{dlq_id}", response_model=DLQEntryResponse)
async def get_dlq_entry(
    dlq_id: UUID,
    _auth: AdminAuthDep,
    use_case: DLQUseCaseDep,
) -> DLQEntryResponse:
    entry = await use_case.get_by_id(dlq_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="DLQ entry not found")
    return _to_response(entry)


@router.post("/{dlq_id}/retry", status_code=202)
async def retry_dlq_entry(
    dlq_id: UUID,
    _auth: AdminAuthDep,
    use_case: DLQUseCaseDep,
) -> dict[str, str]:
    """Requeue a DLQ entry by inserting a new pending outbox event."""
    entry = await use_case.get_by_id(dlq_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="DLQ entry not found")
    new_event_id = await use_case.requeue(entry)
    return {"status": "requeued", "new_event_id": str(new_event_id)}


@router.post("/{dlq_id}/resolve", status_code=200)
async def resolve_dlq_entry(
    dlq_id: UUID,
    body: DLQResolveRequest,
    _auth: AdminAuthDep,
    use_case: DLQUseCaseDep,
) -> dict[str, str]:
    """Mark a DLQ entry as resolved with an optional note."""
    entry = await use_case.get_by_id(dlq_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="DLQ entry not found")
    await use_case.mark_resolved(dlq_id, body.note)
    return {"status": "resolved"}
