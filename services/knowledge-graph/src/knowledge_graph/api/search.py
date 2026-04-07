"""Semantic search endpoints — POST /api/v1/search/relations (Wave C-3).

Read-only endpoint backed by RelationSummarySearchUseCase.
Uses the read-replica session (R27).
"""

from __future__ import annotations

from fastapi import APIRouter

from knowledge_graph.api.dependencies import ReadOnlyDbSessionDep
from knowledge_graph.api.schemas import (
    RelationSearchRequest,
    RelationSearchResponse,
    RelationSearchResultItem,
)
from knowledge_graph.application.use_cases.relation_summary_search import (
    RelationSummarySearchUseCase,
)
from observability import get_logger  # type: ignore[import-untyped]

router = APIRouter(prefix="/api/v1/search", tags=["search"])

_log = get_logger(__name__)  # type: ignore[no-any-return]


@router.post("/relations", response_model=RelationSearchResponse)
async def search_relations(
    body: RelationSearchRequest,
    session: ReadOnlyDbSessionDep,
) -> RelationSearchResponse:
    """ANN search over relation summaries using a query embedding.

    Returns relations ordered by cosine similarity (most similar first).
    ``summary_authority`` is computed at query time as
    ``confidence * log1p(evidence_count)`` — NOT a cached column.
    """
    from knowledge_graph.infrastructure.intelligence_db.repositories.relation_summary import (
        RelationSummaryRepository,
    )

    repo = RelationSummaryRepository(session)
    results = await RelationSummarySearchUseCase().execute(
        repo=repo,  # type: ignore[arg-type]
        query_embedding=body.query_embedding,
        entity_ids=body.entity_ids if body.entity_ids else None,
        min_confidence=body.min_confidence,
        relation_types=body.relation_types if body.relation_types else None,
        semantic_mode=body.semantic_mode,
        top_k=body.top_k,
    )
    return RelationSearchResponse(
        relations=[
            RelationSearchResultItem(
                relation_id=r.relation_id,
                subject=r.subject_canonical_name,
                relation_type=r.canonical_type,
                object=r.object_canonical_name,
                summary=r.summary,
                confidence=r.confidence,
                summary_authority=r.summary_authority,
                evidence_count=r.evidence_count,
                latest_evidence_at=r.latest_evidence_at,
                semantic_mode=r.semantic_mode,
            )
            for r in results
        ]
    )
