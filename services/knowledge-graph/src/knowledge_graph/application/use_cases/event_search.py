"""EventSearchUseCase — query events for a set of entities (Wave C-2).

Read-only use case; depends only on port interfaces, never on infrastructure.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from knowledge_graph.application.ports.event_repository import (
        EventRepositoryPort,
        EventSearchResult,
    )


class EventSearchUseCase:
    """Fetch events for one or more entities with optional filters.

    Returns results ordered by ``event_date DESC``.
    """

    async def execute(
        self,
        event_repo: EventRepositoryPort,
        entity_ids: list,
        *,
        event_types: list[str] | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        top_k: int = 20,
    ) -> list[EventSearchResult]:
        """Return matching :class:`EventSearchResult` instances."""
        return await event_repo.search_events(
            entity_ids=entity_ids,
            event_types=event_types,
            date_from=date_from,
            date_to=date_to,
            top_k=top_k,
        )
