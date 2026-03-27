"""DLQ admin endpoints — list, inspect, retry, resolve (X-Admin-Token required)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select, update

from nlp_pipeline.api.dependencies import AdminAuthDep, NlpDbSessionDep
from nlp_pipeline.api.schemas import DLQEntryResponse, DLQListResponse, DLQResolveRequest
from nlp_pipeline.infrastructure.nlp_db.models import DeadLetterQueueModel, OutboxEventModel

router = APIRouter(prefix="/admin/dlq", tags=["dlq"])


def _to_response(entry: DeadLetterQueueModel) -> DLQEntryResponse:
    return DLQEntryResponse(
        dlq_id=UUID(str(entry.dlq_id)),
        original_event_id=UUID(str(entry.original_event_id)),
        topic=str(entry.topic),
        error_detail=entry.error_detail,
        status=str(entry.status),
        created_at=entry.created_at,
        resolved_at=entry.resolved_at,
        resolution_note=entry.resolution_note,
    )


@router.get("", response_model=DLQListResponse)
async def list_dlq(
    _auth: AdminAuthDep,
    session: NlpDbSessionDep,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> DLQListResponse:
    """List open (unresolved) DLQ entries."""
    q = (
        select(DeadLetterQueueModel)
        .where(DeadLetterQueueModel.status == "failed")
        .order_by(DeadLetterQueueModel.created_at.desc())
    )
    count_q = select(func.count()).select_from(
        select(DeadLetterQueueModel).where(DeadLetterQueueModel.status == "failed").subquery()
    )
    total = (await session.execute(count_q)).scalar_one()

    result = await session.execute(q.limit(limit).offset(offset))
    entries = result.scalars().all()
    return DLQListResponse(
        entries=[_to_response(e) for e in entries],
        total=total,
    )


@router.get("/{dlq_id}", response_model=DLQEntryResponse)
async def get_dlq_entry(
    dlq_id: UUID,
    _auth: AdminAuthDep,
    session: NlpDbSessionDep,
) -> DLQEntryResponse:
    result = await session.execute(select(DeadLetterQueueModel).where(DeadLetterQueueModel.dlq_id == dlq_id))
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="DLQ entry not found")
    return _to_response(entry)


@router.post("/{dlq_id}/retry", status_code=202)
async def retry_dlq_entry(
    dlq_id: UUID,
    _auth: AdminAuthDep,
    session: NlpDbSessionDep,
) -> dict[str, str]:
    """Requeue a DLQ entry by inserting a new pending outbox event."""
    result = await session.execute(select(DeadLetterQueueModel).where(DeadLetterQueueModel.dlq_id == dlq_id))
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="DLQ entry not found")

    import common.ids  # type: ignore[import-untyped]

    new_event_id = common.ids.new_uuid7()
    session.add(
        OutboxEventModel(
            event_id=new_event_id,
            topic=entry.topic,
            partition_key=str(entry.original_event_id),
            payload_avro=entry.payload_avro,
            status="pending",
        )
    )
    await session.commit()
    return {"status": "requeued", "new_event_id": str(new_event_id)}


@router.post("/{dlq_id}/resolve", status_code=200)
async def resolve_dlq_entry(
    dlq_id: UUID,
    body: DLQResolveRequest,
    _auth: AdminAuthDep,
    session: NlpDbSessionDep,
) -> dict[str, str]:
    """Mark a DLQ entry as resolved with an optional note."""
    result = await session.execute(select(DeadLetterQueueModel).where(DeadLetterQueueModel.dlq_id == dlq_id))
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="DLQ entry not found")

    await session.execute(
        update(DeadLetterQueueModel)
        .where(DeadLetterQueueModel.dlq_id == dlq_id)
        .values(
            status="resolved",
            resolved_at=datetime.now(tz=UTC),
            resolution_note=body.note or None,
        )
    )
    await session.commit()
    return {"status": "resolved"}
