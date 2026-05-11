"""Temporal events endpoint — GET /api/v1/temporal-events (PRD-0018 §6.3).

Read-only endpoint backed by ListTemporalEventsUseCase.
Uses the read-replica session (R27 / ReadOnlyDbSessionDep).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import APIRouter, Query

from knowledge_graph.api.dependencies import TemporalEventRepoDep
from knowledge_graph.api.schemas import TemporalEventResponse, TemporalEventsListResponse
from knowledge_graph.application.use_cases.list_temporal_events import ListTemporalEventsUseCase
from observability import get_logger  # type: ignore[import-untyped]

router = APIRouter(prefix="/api/v1", tags=["temporal-events"])

_log = get_logger(__name__)  # type: ignore[no-any-return]


def _lifecycle_phase(
    active_from: datetime,
    active_until: datetime | None,
    residual_impact_days: int,
) -> str:
    """Compute lifecycle phase from raw event timing fields.

    Mirrors ``TemporalEvent.lifecycle_phase`` domain property so that
    the API layer does not need to instantiate the domain dataclass.

    PENDING_ACTIVE — event has not yet started (active_from is in the future)
    ACTIVE         — event is ongoing (active_until is None or in the future)
    RESIDUAL       — event ended; within residual_impact_days window
    EXPIRED        — event ended; residual window has elapsed
    """
    now = datetime.now(UTC)
    if now < active_from:
        return "PENDING_ACTIVE"
    if active_until is None or now <= active_until:
        return "ACTIVE"
    days_since_end = (now - active_until).days
    if days_since_end <= residual_impact_days:
        return "RESIDUAL"
    return "EXPIRED"


@router.get("/temporal-events", response_model=TemporalEventsListResponse)
async def list_temporal_events(
    temporal_event_repo: TemporalEventRepoDep,
    scope: str | None = Query(default=None, max_length=20),
    entity_id: UUID | None = Query(default=None),
    active_only: bool = Query(default=True),
    event_type: str | None = Query(default=None, max_length=50),
    region: str | None = Query(default=None, max_length=100),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> TemporalEventsListResponse:
    """List active or historical temporal events with optional filters.

    Excludes EXPIRED events when ``active_only=true`` (default).
    ``lifecycle_phase`` is computed at query time from the event timing fields —
    it is NOT stored in the database.

    Results ordered by ``active_from DESC``.
    """
    events, total = await ListTemporalEventsUseCase().execute(
        temporal_event_repo,
        scope=scope,
        entity_id=entity_id,
        active_only=active_only,
        event_type=event_type,
        region=region,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )

    return TemporalEventsListResponse(
        events=[
            TemporalEventResponse(
                event_id=row["event_id"],  # type: ignore[arg-type]
                event_type=str(row["event_type"]),
                scope=str(row["scope"]),
                region=str(row["region"]) if row.get("region") else None,
                title=str(row["title"]),
                description=str(row["description"]) if row.get("description") else None,
                active_from=row["active_from"],  # type: ignore[arg-type]
                active_until=row.get("active_until"),  # type: ignore[arg-type]
                residual_impact_days=int(row["residual_impact_days"]),  # type: ignore[call-overload]
                lifecycle_phase=_lifecycle_phase(
                    active_from=row["active_from"],  # type: ignore[arg-type]
                    active_until=row.get("active_until"),  # type: ignore[arg-type]
                    residual_impact_days=int(row["residual_impact_days"]),  # type: ignore[call-overload]
                ),
                confidence=float(row["confidence"]),  # type: ignore[arg-type]
                exposed_entity_count=int(row["exposed_entity_count"]),  # type: ignore[call-overload]
                created_at=row["created_at"],  # type: ignore[arg-type]
            )
            for row in events
        ],
        total=total,
    )
