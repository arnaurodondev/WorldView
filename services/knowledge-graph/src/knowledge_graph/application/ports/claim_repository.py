"""Port interface for claims and contradiction-link queries (Wave C-1).

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
class ClaimSearchResult:
    """A single claim returned by the search use case."""

    claim_id: UUID
    subject_entity_id: UUID
    claim_type: str
    polarity: str
    claim_text: str
    extraction_confidence: float
    doc_id: UUID | None
    created_at: datetime


@dataclasses.dataclass(frozen=True)
class ContradictionSideData:
    """One side of a detected contradiction (polarity / evidence info)."""

    polarity: str
    confidence: float
    doc_id: UUID | None
    claim_text: str
    evidence_date: datetime


@dataclasses.dataclass(frozen=True)
class ContradictionData:
    """A single contradiction entry for an entity (read side of the detection pipeline)."""

    link_id: UUID
    claim_type: str
    strength: float
    detected_at: datetime
    sides: list[ContradictionSideData]


# ── Port ──────────────────────────────────────────────────────────────────────


class ClaimRepositoryPort(ABC):
    """Read-only queries over the ``claims`` and ``relation_contradiction_links`` tables."""

    @abstractmethod
    async def search_claims(
        self,
        entity_ids: list[UUID],
        *,
        claim_types: list[str] | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        min_confidence: float = 0.45,
        top_k: int = 20,
    ) -> list[ClaimSearchResult]: ...

    @abstractmethod
    async def fetch_contradictions_for_entity(
        self,
        entity_id: UUID,
        *,
        claim_type: str | None = None,
        top_k: int = 20,
    ) -> list[ContradictionData]: ...
