"""GetEntityDetailUseCase — read-only entity detail with enrichment fields (PRD-0073 §9.6).

R25 compliance: this use case wraps the CanonicalEntityRepository so that the
API route file never imports from the infrastructure layer directly.
R27 compliance: read-only — uses the read-replica session.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from knowledge_graph.domain.models import CanonicalEntity
    from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
        CanonicalEntityRepository,
    )


class GetEntityDetailUseCase:
    """Return the enriched entity detail for a single canonical entity.

    Args:
        repo: CanonicalEntityRepository bound to a read-only session.
    """

    def __init__(self, repo: CanonicalEntityRepository) -> None:
        self._repo = repo

    async def execute(self, entity_id: UUID) -> CanonicalEntity | None:
        """Fetch and return the entity, or None if it does not exist."""
        return await self._repo.get_by_id(entity_id)
