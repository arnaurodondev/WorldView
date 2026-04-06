"""Fusion pipeline: deduplication + trust-weighted scoring + graph enrichment (T-F-1-02).

Steps 6-7 of the RAG pipeline (PRD §6.7):
  - GraphEnricher: injects top-3 relation summaries adjacent to each chunk
  - FusionPipeline: deduplicates by doc_id (keeps highest fusion_score),
    applies trust weights, sorts DESC, returns top-30 candidates for reranking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from rag_chat.domain.entities.chat import RetrievedItem
from rag_chat.domain.enums import ItemType

if TYPE_CHECKING:
    from rag_chat.application.ports.upstream_clients import RelationResult

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

_MAX_CANDIDATES = 30  # maximum items forwarded to reranking
_MAX_ENTITIES_PER_CHUNK = 2  # max entities enriched per chunk
_MAX_RELATIONS_PER_ENTITY = 3  # top-N relations attached per entity


class GraphEnricher:
    """Attach top-3 relation summaries to chunk items that reference entities.

    For each chunk with entities[], find that entity's top-3 relations from
    the relation_results (ranked by summary_authority) and attach them as
    graph_enrichment on the frozen RetrievedItem (creates a new instance).
    """

    def enrich(
        self,
        items: list[RetrievedItem],
        relation_results: list[RelationResult],
    ) -> list[RetrievedItem]:
        """Return a new list of items with graph context injected into chunks."""
        # Build entity → sorted relations lookup (by summary_authority desc)
        entity_relations: dict[str, list[RelationResult]] = {}
        for rel in relation_results:
            key = rel.subject
            entity_relations.setdefault(key, []).append(rel)
        # Sort each entity's relations by summary_authority (higher is better)
        for key in entity_relations:
            entity_relations[key].sort(
                key=lambda r: r.summary_authority or "",
                reverse=True,
            )

        enriched: list[RetrievedItem] = []
        for item in items:
            if item.item_type != ItemType.chunk:
                enriched.append(item)
                continue
            # Extract entity names from citation_meta (entity_name) or graph_enrichment
            entity_name = item.citation_meta.entity_name
            if not entity_name:
                enriched.append(item)
                continue

            # Collect top-3 relations for up to 2 entities per chunk
            graph_ctx: list[dict] = []
            for _idx, ent_name in enumerate([entity_name]):
                if _idx >= _MAX_ENTITIES_PER_CHUNK:
                    break
                relations = entity_relations.get(ent_name, [])
                for rel in relations[:_MAX_RELATIONS_PER_ENTITY]:
                    graph_ctx.append(
                        {
                            "relation_id": rel.relation_id,
                            "relation_type": rel.relation_type,
                            "subject": rel.subject,
                            "object": rel.object,
                            "summary": rel.summary,
                            "confidence": rel.confidence,
                        }
                    )

            if not graph_ctx:
                enriched.append(item)
                continue

            # Build new frozen item with graph_enrichment attached
            enriched.append(
                RetrievedItem(
                    item_id=item.item_id,
                    item_type=item.item_type,
                    text=item.text,
                    score=item.score,
                    recency_score=item.recency_score,
                    trust_weight=item.trust_weight,
                    fusion_score=item.fusion_score,
                    citation_meta=item.citation_meta,
                    entity_id=item.entity_id,
                    doc_id=item.doc_id,
                    published_at=item.published_at,
                    graph_enrichment=tuple(graph_ctx),
                )
            )
        return enriched


class FusionPipeline:
    """Merge, deduplicate, trust-weight, and rank retrieved items.

    Algorithm (PRD §6.7 Step 7):
    1. For each item: fusion_score = score * recency_score * trust_weight
       (already computed by RetrievedItem.create factory — no recomputation needed)
    2. Deduplicate by doc_id: keep only the item with the highest fusion_score per doc_id
    3. Sort by fusion_score DESC
    4. Return top-30 candidates for the reranking stage
    """

    def process(self, items: list[RetrievedItem]) -> list[RetrievedItem]:
        """Return up to 30 deduplicated items sorted by fusion_score DESC."""
        if not items:
            return []

        # Deduplicate by doc_id — keep highest fusion_score
        best_by_doc: dict[str, RetrievedItem] = {}
        no_doc: list[RetrievedItem] = []
        for item in items:
            if item.doc_id is None:
                no_doc.append(item)
                continue
            doc_key = str(item.doc_id)
            existing = best_by_doc.get(doc_key)
            if existing is None or item.fusion_score > existing.fusion_score:
                best_by_doc[doc_key] = item

        merged = list(best_by_doc.values()) + no_doc
        merged.sort(key=lambda x: x.fusion_score, reverse=True)
        result = merged[:_MAX_CANDIDATES]
        log.debug(  # type: ignore[no-any-return]
            "fusion_complete",
            input_count=len(items),
            after_dedup=len(merged),
            output_count=len(result),
        )
        return result
