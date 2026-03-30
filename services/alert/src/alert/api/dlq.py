"""DLQ admin endpoints for S10.

Protected by ``X-Admin-Token`` header (``ALERT_ADMIN_TOKEN`` env var).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from alert.api.dependencies import AdminAuthDep, DbSessionDep
from alert.api.schemas import DLQEntryResponse, DLQListResponse, DLQResolveRequest
from alert.domain.entities import DeadLetterEntry
from alert.infrastructure.db.repositories.dlq import DLQRepository

router = APIRouter(prefix="/admin/dlq", tags=["dlq"])


def _to_response(entry: DeadLetterEntry) -> DLQEntryResponse:
    return DLQEntryResponse(
        dlq_id=entry.dlq_id,
        original_event_id=entry.original_event_id,
        topic=entry.topic,
        error_detail=entry.error_detail,
        status=str(entry.status),
        created_at=entry.created_at,
        resolved_at=entry.resolved_at,
        resolution_note=entry.resolution_note,
    )


@router.get("", response_model=DLQListResponse)
async def list_dlq(
    _auth: AdminAuthDep,
    session: DbSessionDep,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> DLQListResponse:
    """List failed DLQ entries."""
    repo = DLQRepository(session)
    entries = await repo.list_failed(limit=limit, offset=offset)
    return DLQListResponse(entries=[_to_response(e) for e in entries], total=len(entries))


@router.get("/{dlq_id}", response_model=DLQEntryResponse)
async def get_dlq_entry(
    dlq_id: UUID,
    _auth: AdminAuthDep,
    session: DbSessionDep,
) -> DLQEntryResponse:
    """Get a single DLQ entry."""
    repo = DLQRepository(session)
    entries = await repo.list_failed(limit=1000)
    entry = next((e for e in entries if e.dlq_id == dlq_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="DLQ entry not found")
    return _to_response(entry)


@router.post("/{dlq_id}/resolve", status_code=200)
async def resolve_dlq_entry(
    dlq_id: UUID,
    body: DLQResolveRequest,
    _auth: AdminAuthDep,
    session: DbSessionDep,
) -> dict[str, str]:
    """Mark a DLQ entry as resolved."""
    repo = DLQRepository(session)
    updated = await repo.resolve(dlq_id, resolution_note=body.note)
    if not updated:
        raise HTTPException(status_code=404, detail="DLQ entry not found or already resolved")
    await session.commit()
    return {"status": "resolved"}
