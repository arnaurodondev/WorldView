"""EntityContradictionsUseCase — fetch active contradictions for an entity (Wave C-1).

Read-only use case; depends only on port interfaces, never on infrastructure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from knowledge_graph.application.ports.claim_repository import (
        ClaimRepositoryPort,
        ContradictionData,
    )


class EntityContradictionsUseCase:
    """Return active contradiction links where *entity_id* is the subject.

    Groups results by strength (highest first). Returns an empty list when
    the entity has no recorded contradictions — NOT a 404.
    """

    async def execute(
        self,
        claim_repo: ClaimRepositoryPort,
        entity_id: UUID,
        *,
        claim_type: str | None = None,
        top_k: int = 20,
    ) -> list[ContradictionData]:
        """Return :class:`ContradictionData` list for *entity_id*."""
        return await claim_repo.fetch_contradictions_for_entity(
            entity_id=entity_id,
            claim_type=claim_type,
            top_k=top_k,
        )
