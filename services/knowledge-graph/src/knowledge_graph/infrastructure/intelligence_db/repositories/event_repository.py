"""Events read repository (Wave C-2).

Queries the ``events`` table (RANGE-partitioned by event_date) in
intelligence_db. Reads the new columns added by migration 0002:
  - event_subtype VARCHAR(50) NULL
  - source_type   VARCHAR(50) NULL
  - structured_data JSONB NULL

S7 does NOT own intelligence_db DDL — all queries use raw SQL via ``text()``.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

from knowledge_graph.application.ports.event_repository import (
    EventRepositoryPort,
    EventSearchResult,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class EventRepository(EventRepositoryPort):
    """Read-only access to the ``events`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search_events(
        self,
        entity_ids: list[UUID],
        *,
        event_types: list[str] | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        top_k: int = 20,
    ) -> list[EventSearchResult]:
        """Return events matching the given filters, ordered by ``event_date DESC``.

        Passing an empty ``entity_ids`` list disables the entity filter
        (returns events across all entities, subject to other filters).
        """
        # BP-180: asyncpg raises AmbiguousParameterError when a Python None is
        # bound to a parameter used in "IS NULL" inside a WHERE clause — it cannot
        # infer the PostgreSQL type from None alone.
        # Fix: use CAST(:param AS TYPE) IS NULL so the type is always explicit.
        result = await self._session.execute(
            text("""
SELECT event_id, event_type, event_subtype, subject_entity_id,
       event_date, event_text, structured_data, extraction_confidence,
       doc_id, source_type
FROM events
WHERE (CAST(:entity_ids AS UUID[]) IS NULL OR subject_entity_id = ANY(CAST(:entity_ids AS UUID[])))
  AND (CAST(:event_types AS TEXT[]) IS NULL OR event_type = ANY(CAST(:event_types AS TEXT[])))
  AND (CAST(:date_from AS DATE) IS NULL OR event_date >= CAST(:date_from AS DATE))
  AND (CAST(:date_to   AS DATE) IS NULL OR event_date <= CAST(:date_to   AS DATE))
ORDER BY event_date DESC
LIMIT :top_k
"""),
            {
                "entity_ids": [str(e) for e in entity_ids] if entity_ids else None,
                "event_types": event_types if event_types else None,
                "date_from": date_from,
                "date_to": date_to,
                "top_k": top_k,
            },
        )
        rows = result.fetchall()
        return [
            EventSearchResult(
                event_id=UUID(str(r[0])),
                event_type=str(r[1]),
                event_subtype=str(r[2]) if r[2] is not None else None,
                subject_entity_id=UUID(str(r[3])),
                event_date=r[4],
                event_text=str(r[5]),
                structured_data=dict(r[6]) if r[6] is not None else None,
                extraction_confidence=float(r[7]),
                doc_id=UUID(str(r[8])) if r[8] else None,
                source_type=str(r[9]) if r[9] is not None else None,
            )
            for r in rows
        ]
