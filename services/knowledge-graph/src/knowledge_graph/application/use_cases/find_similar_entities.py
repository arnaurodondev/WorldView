"""FindSimilarEntitiesUseCase — ANN + competes_with boost algorithm (PRD-0017 §6.5).

Algorithm:
  1. Fetch query entity (404 if not found).
  2. Fetch fundamentals_ohlcv embedding (422 if absent).
  3. ANN search: find_nearest(embedding, view_type='fundamentals_ohlcv',
                              limit=top_k*2, entity_types=['financial_instrument'],
                              exclude_entity_id=entity_id).
  4. Transform distances → ann_similarity_score = 1.0 - distance.
  5. Batch-fetch competes_with relations: find_competes_with_batch(entity_id, candidate_ids).
  6. Compute final_score = min(ann_similarity_score + (0.15 if competes_with else 0.0), 1.0).
  7. Filter by min_score; apply include_competitors_only.
  8. Sort by final_score DESC; take top_k.
  9. Batch-enrich entity details via get_batch() — single query.
 10. Return (entity_dict, list[SimilarEntityResult]).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from knowledge_graph.application.ports.repositories import (
        CanonicalEntityRepositoryPort,
        EntityEmbeddingANNRepositoryPort,
        RelationRepositoryPort,
    )
    from knowledge_graph.domain.models import SimilarEntityResult

_VIEW_TYPE = "fundamentals_ohlcv"
_COMPETES_WITH_BOOST = 0.15
_COMPETES_WITH_MIN_CONFIDENCE = 0.3
_FINANCIAL_INSTRUMENT_TYPES = ["financial_instrument"]


class FindSimilarEntitiesUseCase:
    """Find similar financial instrument entities by fundamentals_ohlcv ANN."""

    async def execute(
        self,
        entity_repo: CanonicalEntityRepositoryPort,
        embedding_repo: EntityEmbeddingANNRepositoryPort,
        relation_repo: RelationRepositoryPort,
        entity_id: UUID,
        top_k: int = 20,
        min_score: float = 0.0,
        include_competitors_only: bool = False,
    ) -> tuple[dict[str, object], list[SimilarEntityResult]]:
        """Return ``(query_entity_dict, ranked_results)``.

        Raises:
            EntityNotFoundError: if entity_id does not exist.
            EmbeddingNotAvailableError: if the entity has no fundamentals_ohlcv embedding.
        """
        from knowledge_graph.domain.errors import EmbeddingNotAvailableError, EntityNotFoundError
        from knowledge_graph.domain.models import SimilarEntityResult

        # Step 1 — fetch query entity
        entity_dict = await entity_repo.get(entity_id)
        if entity_dict is None:
            raise EntityNotFoundError(f"Entity {entity_id!r} not found")

        # Step 2 — fetch embedding (None → 422)
        embedding = await embedding_repo.get_embedding(entity_id, _VIEW_TYPE)
        if embedding is None:
            raise EmbeddingNotAvailableError(entity_id, _VIEW_TYPE)

        # Step 3 — ANN search: oversample by 2x to allow post-filter
        ann_results = await embedding_repo.find_nearest(
            query_embedding=embedding,
            view_type=_VIEW_TYPE,
            limit=top_k * 2,
            exclude_entity_id=entity_id,
            entity_types=_FINANCIAL_INSTRUMENT_TYPES,
        )

        if not ann_results:
            return entity_dict, []

        # Steps 4 & 5 — batch fetch competes_with relations (step 4 distance→similarity
        # happens inline in the scoring loop below)
        candidate_ids = [r.entity_id for r in ann_results]
        competes_map = await relation_repo.find_competes_with_batch(
            entity_id=entity_id,
            candidate_ids=candidate_ids,
            min_confidence=_COMPETES_WITH_MIN_CONFIDENCE,
        )

        # Steps 6 / 7 / 8 — score, filter, sort
        scored: list[tuple[float, SimilarEntityResult]] = []
        for ann in ann_results:
            ann_similarity = max(0.0, 1.0 - ann.distance)
            competes_entry = competes_map.get(ann.entity_id)
            has_competes = competes_entry is not None
            competes_confidence = competes_entry[1] if competes_entry is not None else None
            boost = _COMPETES_WITH_BOOST if has_competes else 0.0
            final_score = min(ann_similarity + boost, 1.0)

            if final_score < min_score:
                continue
            if include_competitors_only and not has_competes:
                continue

            # Placeholder entity data; enriched in step 9
            scored.append(
                (
                    final_score,
                    SimilarEntityResult(
                        entity_id=ann.entity_id,
                        canonical_name="",  # filled below
                        entity_type="financial_instrument",
                        ticker=None,
                        exchange=None,
                        ann_similarity_score=ann_similarity,
                        competes_with_confidence=competes_confidence,
                        final_score=final_score,
                        has_competes_with_relation=has_competes,
                    ),
                )
            )

        # Step 8 — sort by final_score DESC, take top_k
        scored.sort(key=lambda t: t[0], reverse=True)
        top_scored = scored[:top_k]

        # Step 9 — batch-enrich entity details (single WHERE entity_id = ANY(:ids) query)
        top_entity_ids = [partial.entity_id for _, partial in top_scored]
        batch = await entity_repo.get_batch(top_entity_ids)
        detail_map: dict[object, dict[str, object]] = {d["entity_id"]: d for d in batch}

        results: list[SimilarEntityResult] = []
        for _, partial in top_scored:
            detail = detail_map.get(partial.entity_id)
            if detail is None:
                # Entity disappeared between ANN query and now — skip silently
                continue
            results.append(
                SimilarEntityResult(
                    entity_id=partial.entity_id,
                    canonical_name=str(detail.get("canonical_name", "")),
                    entity_type=str(detail.get("entity_type", "financial_instrument")),
                    ticker=str(detail["ticker"]) if detail.get("ticker") else None,
                    exchange=str(detail["exchange"]) if detail.get("exchange") else None,
                    ann_similarity_score=partial.ann_similarity_score,
                    competes_with_confidence=partial.competes_with_confidence,
                    final_score=partial.final_score,
                    has_competes_with_relation=partial.has_competes_with_relation,
                )
            )

        return entity_dict, results
