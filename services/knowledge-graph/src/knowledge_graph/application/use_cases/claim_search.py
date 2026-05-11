"""ArticleClaimSearchUseCase — query claims for a set of entities (Wave C-1).

Read-only use case; depends only on port interfaces, never on infrastructure.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from knowledge_graph.application.ports.claim_repository import (
        ClaimRepositoryPort,
        ClaimSearchResult,
    )


class ArticleClaimSearchUseCase:
    """Fetch claims for one or more entities with optional filters.

    Returns results ordered by ``extraction_confidence DESC``.
    """

    async def execute(
        self,
        claim_repo: ClaimRepositoryPort,
        entity_ids: list,
        *,
        claim_types: list[str] | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        min_confidence: float = 0.45,
        top_k: int = 20,
    ) -> list[ClaimSearchResult]:
        """Return matching :class:`ClaimSearchResult` instances."""
        return await claim_repo.search_claims(
            entity_ids=entity_ids,
            claim_types=claim_types,
            date_from=date_from,
            date_to=date_to,
            min_confidence=min_confidence,
            top_k=top_k,
        )
