"""Port interface for events queries (Wave C-2).

Use cases depend only on this ABC — never on infrastructure classes directly.
No infrastructure imports are permitted in this module.
"""

from __future__ import annotations

import dataclasses
from abc import ABC, abstractmethod
from datetime import date, datetime
from uuid import UUID

# ── Value objects ─────────────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class EventSearchResult:
    """A single event returned by the search use case."""

    event_id: UUID
    event_type: str
    event_subtype: str | None
    subject_entity_id: UUID
    event_date: datetime | None
    event_text: str
    structured_data: dict | None
    extraction_confidence: float
    doc_id: UUID | None
    source_type: str | None


# ── Port ──────────────────────────────────────────────────────────────────────


class EventRepositoryPort(ABC):
    """Read-only queries over the ``events`` table."""

    @abstractmethod
    async def search_events(
        self,
        entity_ids: list[UUID],
        *,
        event_types: list[str] | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        top_k: int = 20,
    ) -> list[EventSearchResult]: ...
