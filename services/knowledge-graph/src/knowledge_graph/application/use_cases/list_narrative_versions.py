"""ListNarrativeVersionsUseCase — paginated history of entity narrative versions.

R25 compliance: wraps NarrativeRepository so API route files never import infra.
R27 compliance: read-only — uses the read-replica session throughout.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from knowledge_graph.api.schemas_intelligence import NarrativeVersionListResponse
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
    ) -> NarrativeVersionListResponse:
        """Return paginated narrative versions, newest first.

        Delegates to NarrativeRepository.list_versions which uses keyset
        pagination on (generated_at DESC, version_id).

        Returns NarrativeVersionListResponse with versions + next_cursor.
        """
        from knowledge_graph.api.schemas_intelligence import (
            NarrativeVersionListResponse,
            NarrativeVersionPublic,
        )

        versions, next_cursor = await self._narrative_repo.list_versions(
            entity_id=entity_id,
            tenant_id=tenant_id,
            limit=limit,
            cursor=cursor,
        )

        return NarrativeVersionListResponse(
            entity_id=entity_id,
            versions=[
                NarrativeVersionPublic(
                    version_id=v.version_id,
                    narrative_text=v.narrative_text,
                    model_id=v.model_id,
                    generation_reason=v.generation_reason.value,
                    generated_at=v.generated_at,
                    word_count=v.word_count,
                    quality_score=v.quality_score,
                )
                for v in versions
            ],
            next_cursor=next_cursor,
        )
