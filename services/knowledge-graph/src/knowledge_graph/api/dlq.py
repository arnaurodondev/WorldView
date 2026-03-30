"""DLQ admin endpoints — list, inspect, and resolve dead-letter entries.

All endpoints require the ``X-Admin-Token`` header matching
``settings.admin_token``.
"""

from __future__ import annotations

import hmac
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import text

from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.api.schemas import DLQEntryResponse, DLQListResponse, DLQResolveRequest
from observability import get_logger  # type: ignore[import-untyped]

router = APIRouter(prefix="/admin/dlq", tags=["dlq"])
_log = get_logger(__name__)  # type: ignore[no-any-return]


async def _require_admin(
    request: Request,
    x_admin_token: Annotated[str | None, Header()] = None,
) -> None:
    """Validate the X-Admin-Token header."""
    expected: str = getattr(request.app.state, "admin_token", "")
    provided: str = x_admin_token or ""
    if not expected or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


AdminAuth = Annotated[None, Depends(_require_admin)]


@router.get("", response_model=DLQListResponse)
async def list_dlq(
    request: Request,
    _auth: AdminAuth,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> DLQListResponse:
    """List open DLQ entries (status = 'failed')."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        result = await session.execute(
            text("""
SELECT dlq_id, original_event_id, topic, error_detail, status,
       created_at, resolved_at, resolution_note
FROM dead_letter_queue
WHERE status = 'failed'
ORDER BY created_at DESC
LIMIT :limit OFFSET :offset
"""),
            {"limit": limit, "offset": offset},
        )
        rows = result.fetchall()

        count_result = await session.execute(text("SELECT COUNT(*) FROM dead_letter_queue WHERE status = 'failed'"))
        total = int(count_result.scalar() or 0)

    entries = [
        DLQEntryResponse(
            dlq_id=UUID(str(r[0])),
            original_event_id=UUID(str(r[1])),
            topic=str(r[2]),
            error_detail=str(r[3]),
            status=str(r[4]),
            created_at=r[5],
            resolved_at=r[6],
            resolution_note=r[7],
        )
        for r in rows
    ]
    return DLQListResponse(entries=entries, count=total)


@router.get("/{dlq_id}", response_model=DLQEntryResponse)
async def get_dlq_entry(
    dlq_id: UUID,
    request: Request,
    _auth: AdminAuth,
) -> DLQEntryResponse:
    """Get a single DLQ entry."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        result = await session.execute(
            text("""
SELECT dlq_id, original_event_id, topic, error_detail, status,
       created_at, resolved_at, resolution_note
FROM dead_letter_queue
WHERE dlq_id = :dlq_id
"""),
            {"dlq_id": str(dlq_id)},
        )
        row = result.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="DLQ entry not found")

    return DLQEntryResponse(
        dlq_id=UUID(str(row[0])),
        original_event_id=UUID(str(row[1])),
        topic=str(row[2]),
        error_detail=str(row[3]),
        status=str(row[4]),
        created_at=row[5],
        resolved_at=row[6],
        resolution_note=row[7],
    )


@router.post("/{dlq_id}/resolve", status_code=200)
async def resolve_dlq_entry(
    dlq_id: UUID,
    body: DLQResolveRequest,
    request: Request,
    _auth: AdminAuth,
) -> dict[str, str]:
    """Mark a DLQ entry as resolved with an optional note."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        result = await session.execute(
            text("""
UPDATE dead_letter_queue
SET status = 'resolved', resolved_at = :now, resolution_note = :note
WHERE dlq_id = :dlq_id
RETURNING dlq_id
"""),
            {"dlq_id": str(dlq_id), "now": utc_now(), "note": body.note or None},  # type: ignore[no-any-return]
        )
        row = result.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="DLQ entry not found")
        await session.commit()

    return {"status": "resolved"}
