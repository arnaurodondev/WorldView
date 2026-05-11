"""ListNarrativeVersionsUseCase — paginated history of entity narrative versions.

R25 compliance: wraps NarrativeRepository so API route files never import infra.
R27 compliance: read-only — uses the read-replica session throughout.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from knowledge_graph.domain.narrative import EntityNarrativeVersion
    from knowledge_graph.infrastructure.intelligence_db.repositories.narrative_repository import (
        NarrativeRepository,
    )


class ListNarrativeVersionsUseCase:
    """Return paginated narrative version history for an entity.

    Args:
        narrative_repo: NarrativeRepository bound to a read-only session.
    """

    def __init__(self, narrative_repo: NarrativeRepository) -> None:
        self._narrative_repo = narrative_repo

    async def execute(
        self,
        entity_id: UUID,
        tenant_id: UUID | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> tuple[list[EntityNarrativeVersion], str | None]:
        """Return paginated narrative versions, newest first.

        Delegates to NarrativeRepository.list_versions which uses keyset
        pagination on (generated_at DESC, version_id).

        Returns a tuple of (versions, next_cursor).  The API layer is
        responsible for mapping domain types to the wire-format response schema
        (R12 — application layer must not import from api/).
        """
        return await self._narrative_repo.list_versions(
            entity_id=entity_id,
            tenant_id=tenant_id,
            limit=limit,
            cursor=cursor,
        )
