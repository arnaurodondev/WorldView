"""ListTemporalEventsUseCase — list active temporal events (PRD-0018 §6.3).

Read-only use case; depends only on port interfaces, never on infrastructure.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from knowledge_graph.application.ports.temporal_event_repository import (
        TemporalEventRepositoryPort,
    )


class ListTemporalEventsUseCase:
    """Fetch temporal events with flexible filters.

    Returns results ordered by ``active_from DESC``.
    """

    async def execute(
        self,
        temporal_event_repo: TemporalEventRepositoryPort,
        *,
        scope: str | None = None,
        entity_id: UUID | None = None,
        active_only: bool = True,
        event_type: str | None = None,
        region: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, object]], int]:
        """Return matching temporal events and total count.

        Args:
            temporal_event_repo: Port implementation for temporal_events queries.
            scope:       Filter by EventScope (LOCAL/REGIONAL/NATIONAL/GLOBAL).
            entity_id:   If set, only events where entity is in entity_event_exposures.
            active_only: If True (default), exclude EXPIRED events.
            event_type:  Filter by event_type string.
            region:      Filter by region tag (ISO-3166 alpha-2 or special value).
            from_date:   Events with active_from >= this date.
            to_date:     Events with active_from <= this date.
            limit:       Page size (1-200).
            offset:      Pagination offset (≥ 0).

        Returns:
            Tuple of (event_dicts, total_count).
        """
        return await temporal_event_repo.list_active(
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
