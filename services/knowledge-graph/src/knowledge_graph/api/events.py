"""Events search endpoint — POST /api/v1/events/search (Wave C-2).

Read-only endpoint backed by EventSearchUseCase.
Uses the read-replica session (R27).
"""

from __future__ import annotations

from fastapi import APIRouter

from knowledge_graph.api.dependencies import ReadOnlyDbSessionDep
from knowledge_graph.api.schemas import (
    EventResponse,
    EventsSearchRequest,
    EventsSearchResponse,
)
from knowledge_graph.application.use_cases.event_search import EventSearchUseCase
from observability import get_logger  # type: ignore[import-untyped]

router = APIRouter(prefix="/api/v1", tags=["events"])

_log = get_logger(__name__)  # type: ignore[no-any-return]


@router.post("/events/search", response_model=EventsSearchResponse)
async def search_events(
    body: EventsSearchRequest,
    session: ReadOnlyDbSessionDep,
) -> EventsSearchResponse:
    """Search events for a set of entities with optional filters.

    Returns events ordered by ``event_date DESC``.
    Includes ``structured_data`` and ``event_subtype`` added by migration 0002.
    Omitting ``entity_ids`` (or passing an empty list) returns events
    across all entities subject to the other filters.
    """
    from knowledge_graph.infrastructure.intelligence_db.repositories.event_repository import (
        EventRepository,
    )

    event_repo = EventRepository(session)
    results = await EventSearchUseCase().execute(
        event_repo=event_repo,  # type: ignore[arg-type]
        entity_ids=body.entity_ids,
        event_types=body.event_types if body.event_types else None,
        date_from=body.date_from,
        date_to=body.date_to,
        top_k=body.top_k,
    )
    return EventsSearchResponse(
        events=[
            EventResponse(
                event_id=r.event_id,
                event_type=r.event_type,
                event_subtype=r.event_subtype,
                subject_entity_id=r.subject_entity_id,
                event_date=r.event_date,
                event_text=r.event_text,
                structured_data=r.structured_data,
                extraction_confidence=r.extraction_confidence,
                doc_id=r.doc_id,
            )
            for r in results
        ]
    )
