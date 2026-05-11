"""RelationSummarySearchUseCase — ANN search over relation summaries (Wave C-3).

Read-only use case; depends only on port interfaces, never on infrastructure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from knowledge_graph.application.ports.relation_summary_repository import (
        RelationSummaryRepositoryPort,
        RelationSummarySearchResult,
    )


class RelationSummarySearchUseCase:
    """Fetch relations ranked by semantic similarity to a query embedding.

    Returns results ordered by cosine distance ASC (most similar first).
    ``summary_authority`` is computed by the repository at fetch time.
    """

    async def execute(
        self,
        repo: RelationSummaryRepositoryPort,
        query_embedding: list[float],
        *,
        entity_ids: list | None = None,
        min_confidence: float = 0.30,
        relation_types: list[str] | None = None,
        semantic_mode: str | None = None,
        top_k: int = 15,
    ) -> list[RelationSummarySearchResult]:
        """Return matching :class:`RelationSummarySearchResult` instances."""
        return await repo.search_by_embedding(
            query_embedding=query_embedding,
            entity_ids=entity_ids,
            min_confidence=min_confidence,
            relation_types=relation_types,
            semantic_mode=semantic_mode,
            top_k=top_k,
        )
