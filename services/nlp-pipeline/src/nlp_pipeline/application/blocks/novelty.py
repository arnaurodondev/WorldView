"""Block 8 — Novelty gate (PRD §6.7 Block 8).

2-stage novelty detection:
  Stage 1 — MinHash/Valkey LSH similarity check (threshold 0.80).
             Uses pre-computed MinHash signature stored by S5.
  Stage 2 — Per-entity embedding similarity against recent content.
             Downgrades DEEP→LIGHT when ALL resolved entities are near-duplicates.

Cross-DB: reads from S5 Valkey cache (never direct DB access to S5).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog  # type: ignore[import-untyped]

from nlp_pipeline.domain.enums import RoutingTier

if TYPE_CHECKING:
    from uuid import UUID

    from nlp_pipeline.domain.models import RoutingDecision

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# ── Novelty thresholds (PRD §6.7 Block 8) ────────────────────────────────────

#: MinHash similarity above this → near-duplicate (Stage 1)
MINHASH_SIMILARITY_THRESHOLD: float = 0.80

#: Per-entity embedding cosine similarity above this → entity near-duplicate (Stage 2)
EMBEDDING_SIMILARITY_THRESHOLD: float = 0.90

#: Valkey key prefix used by S5 for article MinHash signatures
_S5_MINHASH_KEY_PREFIX: str = "s5:minhash:article:"


# ── Stage 1: MinHash / Valkey LSH ────────────────────────────────────────────


async def _get_minhash_similarity(
    doc_id: UUID,
    *,
    valkey_client: object,  # ValkeyClient — typed as object to avoid hard dep
) -> float | None:
    """Retrieve the pre-computed MinHash similarity score stored by S5.

    S5 stores the highest Jaccard similarity to recent articles in Valkey
    as a float under key ``s5:minhash:article:<doc_id>``.

    Returns None if the key is absent (treated as novel by caller).
    """
    try:
        key = f"{_S5_MINHASH_KEY_PREFIX}{doc_id}"
        # ValkeyClient.get returns bytes or None
        raw = await valkey_client.get(key)  # type: ignore[attr-defined]
        if raw is None:
            return None
        return float(raw)
    except Exception:
        # Best-effort — Valkey unavailable → treat as novel
        logger.warning("novelty.minhash_lookup_failed", doc_id=str(doc_id))
        return None


# ── Stage 2: Per-entity embedding similarity ─────────────────────────────────


async def _all_entities_near_duplicate(
    resolved_entity_ids: list[UUID],
    *,
    entity_profile_embedding_repo: object,  # EntityProfileEmbeddingRepository
    query_embeddings: dict[UUID, list[float]],  # entity_id → embedding
) -> bool:
    """Check whether ALL resolved entities are near-duplicates of recent content.

    Uses ANN search against entity_embedding_state restricted to the
    ``narrative`` view (temporal similarity, not identity).

    Returns True only if every entity in the list has a cosine similarity
    ≥ EMBEDDING_SIMILARITY_THRESHOLD against at least one recent embedding.
    """
    if not resolved_entity_ids:
        return False

    near_dup_count = 0
    for entity_id in resolved_entity_ids:
        embedding = query_embeddings.get(entity_id)
        if embedding is None:
            # No embedding available — assume novel
            continue
        try:
            results = await entity_profile_embedding_repo.ann_search(  # type: ignore[attr-defined]
                embedding,
                view_type="narrative",
                max_distance=1.0 - EMBEDDING_SIMILARITY_THRESHOLD,
                top_k=1,
            )
            if results:
                near_dup_count += 1
        except Exception:
            logger.warning("novelty.embedding_search_failed", entity_id=str(entity_id))

    return near_dup_count == len(resolved_entity_ids) and len(resolved_entity_ids) > 0


# ── Main block entry point ────────────────────────────────────────────────────


async def run_novelty_gate(
    doc_id: UUID,
    routing_decision: RoutingDecision,
    *,
    valkey_client: object,
    entity_profile_embedding_repo: object,
    resolved_entity_ids: list[UUID],
    entity_embeddings: dict[UUID, list[float]],
) -> tuple[RoutingDecision, float]:
    """Apply the 2-stage novelty gate and optionally downgrade DEEP→LIGHT.

    Stage 1: MinHash LSH — if similarity ≥ MINHASH_SIMILARITY_THRESHOLD
             AND routing_decision.routing_tier is DEEP → downgrade to LIGHT.
    Stage 2: Per-entity embedding similarity — if ALL entities are
             near-duplicates → downgrade DEEP→LIGHT.

    The ``final_routing_tier`` field on the returned RoutingDecision is set
    when a downgrade occurs; otherwise it remains None.

    Returns:
        (updated_routing_decision, novelty_score [0.0 - 1.0])
        novelty_score = 1.0 means fully novel, 0.0 means certain duplicate.
        Range [0.0 - 1.0].
    """
    novelty_score: float = 1.0

    # ── Stage 1 — MinHash ────────────────────────────────────────────────────
    minhash_sim = await _get_minhash_similarity(doc_id, valkey_client=valkey_client)

    if minhash_sim is not None:
        novelty_score = max(0.0, 1.0 - minhash_sim)
        if minhash_sim >= MINHASH_SIMILARITY_THRESHOLD and routing_decision.routing_tier == RoutingTier.DEEP:
            logger.info(
                "novelty.stage1_downgrade",
                doc_id=str(doc_id),
                minhash_sim=minhash_sim,
            )
            routing_decision.final_routing_tier = RoutingTier.LIGHT
            return routing_decision, novelty_score

    # ── Stage 2 — Per-entity embedding similarity ─────────────────────────────
    if routing_decision.routing_tier == RoutingTier.DEEP and resolved_entity_ids:
        all_dup = await _all_entities_near_duplicate(
            resolved_entity_ids,
            entity_profile_embedding_repo=entity_profile_embedding_repo,
            query_embeddings=entity_embeddings,
        )
        if all_dup:
            logger.info(
                "novelty.stage2_downgrade",
                doc_id=str(doc_id),
                entity_count=len(resolved_entity_ids),
            )
            routing_decision.final_routing_tier = RoutingTier.LIGHT
            novelty_score = 0.0

    return routing_decision, novelty_score
