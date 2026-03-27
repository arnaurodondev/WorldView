"""DLQ admin endpoints — list, inspect, retry, resolve."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from content_store.api.dependencies import AdminAuthDep, DbSessionDep
from content_store.api.schemas import DLQEntryResponse, DLQListResponse, DLQResolveRequest
from content_store.infrastructure.db.repositories.dlq import DLQRepository

router = APIRouter(prefix="/admin/dlq", tags=["dlq"])


def _dlq_to_response(entry: object) -> DLQEntryResponse:
    return DLQEntryResponse(
        dlq_id=entry.dlq_id,  # type: ignore[attr-defined]
        original_event_id=entry.original_event_id,  # type: ignore[attr-defined]
        topic=entry.topic,  # type: ignore[attr-defined]
        error_detail=entry.error_detail,  # type: ignore[attr-defined]
        status=entry.status,  # type: ignore[attr-defined]
        created_at=entry.created_at,  # type: ignore[attr-defined]
        resolved_at=entry.resolved_at,  # type: ignore[attr-defined]
        resolution_note=entry.resolution_note,  # type: ignore[attr-defined]
    )


@router.get("", response_model=DLQListResponse)
async def list_dlq(
    _auth: AdminAuthDep,
    session: DbSessionDep,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> DLQListResponse:
    """List open DLQ entries."""
    repo = DLQRepository(session)
    entries, total = await repo.list_open(limit=limit, offset=offset)
    return DLQListResponse(
        entries=[_dlq_to_response(e) for e in entries],
        count=total,
    )


@router.get("/{dlq_id}", response_model=DLQEntryResponse)
async def get_dlq_entry(
    dlq_id: UUID,
    _auth: AdminAuthDep,
    session: DbSessionDep,
) -> DLQEntryResponse:
    """Get a single DLQ entry with full payload."""
    repo = DLQRepository(session)
    entry = await repo.get_by_id(dlq_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="DLQ entry not found")
    return _dlq_to_response(entry)


@router.post("/{dlq_id}/retry", status_code=202)
async def retry_dlq_entry(
    dlq_id: UUID,
    _auth: AdminAuthDep,
    session: DbSessionDep,
) -> dict[str, str]:
    """Requeue a DLQ entry back into the outbox."""
    repo = DLQRepository(session)
    entry = await repo.get_by_id(dlq_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="DLQ entry not found")
    new_id = await repo.requeue(dlq_id)
    await session.commit()
    return {"status": "requeued", "new_event_id": str(new_id)}


@router.post("/{dlq_id}/resolve", status_code=200)
async def resolve_dlq_entry(
    dlq_id: UUID,
    body: DLQResolveRequest,
    _auth: AdminAuthDep,
    session: DbSessionDep,
) -> dict[str, str]:
    """Mark a DLQ entry as resolved with a note."""
    repo = DLQRepository(session)
    entry = await repo.get_by_id(dlq_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="DLQ entry not found")
    await repo.mark_resolved(dlq_id, note=body.note)
    await session.commit()
    return {"status": "resolved"}
