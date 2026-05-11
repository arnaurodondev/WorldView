"""Port interface for entity enrichment persistence (PRD-0073 §9.4).

No infrastructure imports permitted in this module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from knowledge_graph.domain.enrichment_result import EnrichmentResult
    from knowledge_graph.domain.models import CanonicalEntity


class EntityEnrichmentPort(Protocol):
    """Port for persisting enrichment results and querying unenriched entities.

    Concrete implementation: ``EntityEnrichmentAdapter`` in the infrastructure layer.
    All methods that accept a ``session`` use a caller-provided session so the use
    case controls the transaction boundary (R25 3-phase pattern).
    ``list_unenriched`` opens its own session — it is called in Phase 1 (before HTTP
    calls) and must not hold a session during external I/O.
    """

    async def write_enrichment_result(
        self,
        result: EnrichmentResult,
        session: AsyncSession,
    ) -> None:
        """Persist a completed EnrichmentResult; caller commits the session."""
        ...

    async def increment_attempts(
        self,
        entity_id: UUID,
        session: AsyncSession,
    ) -> None:
        """Increment enrichment_attempts by 1 for a failed entity; caller commits."""
        ...

    async def list_unenriched(
        self,
        batch_size: int,
    ) -> list[CanonicalEntity]:
        """Return up to batch_size entities needing enrichment.

        Opens and closes its own DB session — must not be called while an
        external HTTP or LLM call is in flight (R25 §10.2).
        """
        ...
