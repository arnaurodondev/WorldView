"""Port interface for relation summary ANN search (Wave C-3).

Use cases depend only on this ABC — never on infrastructure classes directly.
No infrastructure imports are permitted in this module.
"""

from __future__ import annotations

import dataclasses
from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

# ── Value objects ─────────────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class RelationSummarySearchResult:
    """A single relation returned by the ANN search use case.

    ``summary_authority`` is computed in Python as
    ``confidence * log1p(evidence_count)`` — it is NOT a stored DB column.
    """

    relation_id: UUID
    subject_entity_id: UUID
    object_entity_id: UUID
    subject_canonical_name: str
    object_canonical_name: str
    canonical_type: str
    summary: str
    confidence: float
    evidence_count: int
    latest_evidence_at: datetime | None
    semantic_mode: str
    summary_authority: float


# ── Port ──────────────────────────────────────────────────────────────────────


class RelationSummaryRepositoryPort(ABC):
    """Read-only ANN search over ``relation_summaries``."""

    @abstractmethod
    async def search_by_embedding(
        self,
        query_embedding: list[float],
        *,
        entity_ids: list[UUID] | None = None,
        min_confidence: float = 0.30,
        relation_types: list[str] | None = None,
        semantic_mode: str | None = None,
        top_k: int = 15,
    ) -> list[RelationSummarySearchResult]: ...
