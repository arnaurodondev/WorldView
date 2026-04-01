"""Block 9 — Entity resolution cascade (PRD §6.7 Block 9).

4-step cascade per PRD §6.7 Block 9:
  1. Exact alias match (confidence 1.0)
  2. Ticker/ISIN match (confidence 0.95)
  3. Fuzzy trigram similarity > 0.75 (confidence = sim * 0.90)
  4. ANN HNSW on entity_embedding_state WHERE view_type='definition'
     (cosine distance < 0.35, clear margin > 0.10, confidence = (1-dist)*0.80)

Resolution thresholds:
  AUTO_RESOLVE  ≥ 0.72 → write entity_mentions.resolved_entity_id
  PROVISIONAL   ≥ 0.45 → INSERT provisional_entity_queue (UNIQUE on surface+class)
  UNRESOLVED    < 0.45 → preserve mention, NEVER discard

Writes mention_resolutions audit trail for every attempted stage.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog  # type: ignore[import-untyped]

import common.ids  # type: ignore[import-untyped]
from nlp_pipeline.domain.enums import ResolutionOutcome
from nlp_pipeline.domain.models import EntityMention, MentionResolution

if TYPE_CHECKING:
    from uuid import UUID

    from ml_clients.protocols import EmbeddingClient  # type: ignore[import-not-found]

    from nlp_pipeline.infrastructure.intelligence_db.repositories.canonical_entity import CanonicalEntityRepository
    from nlp_pipeline.infrastructure.intelligence_db.repositories.entity_alias import EntityAliasRepository
    from nlp_pipeline.infrastructure.intelligence_db.repositories.entity_profile_embedding import (
        EntityProfileEmbeddingRepository,
    )
    from nlp_pipeline.infrastructure.nlp_db.repositories.mention_resolution import MentionResolutionRepository

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# ── Resolution thresholds (PRD §6.7 Block 9) ─────────────────────────────────

AUTO_RESOLVE_THRESHOLD: float = 0.72
PROVISIONAL_THRESHOLD: float = 0.45

# ── Stage confidences ─────────────────────────────────────────────────────────

CONFIDENCE_EXACT: float = 1.0
CONFIDENCE_TICKER_ISIN: float = 0.95
FUZZY_CONFIDENCE_MULTIPLIER: float = 0.90
ANN_CONFIDENCE_MULTIPLIER: float = 0.80

# ── ANN resolution thresholds (PRD §6.7 Block 9 Stage 4) ─────────────────────

ANN_MAX_DISTANCE: float = 0.35
ANN_CLEAR_MARGIN: float = 0.10


# ── Stage implementations ─────────────────────────────────────────────────────


async def _stage1_exact(
    mention: EntityMention,
    alias_repo: EntityAliasRepository,
    audit: list[MentionResolution],
) -> tuple[UUID | None, float]:
    """Stage 1 — exact alias match."""
    entity_id = await alias_repo.exact_match(mention.mention_text)
    audit.append(
        MentionResolution(
            mention_id=mention.mention_id,
            stage=1,
            score=CONFIDENCE_EXACT if entity_id else 0.0,
            is_winner=entity_id is not None,
            candidate_entity_id=entity_id,
            metadata={"method": "exact_alias"},
        ),
    )
    if entity_id:
        return entity_id, CONFIDENCE_EXACT
    return None, 0.0


async def _stage2_ticker_isin(
    mention: EntityMention,
    alias_repo: EntityAliasRepository,
    audit: list[MentionResolution],
) -> tuple[UUID | None, float]:
    """Stage 2 — ticker/ISIN match against canonical_entities."""
    # Attempt to parse ticker from the mention text (bare uppercase word)
    text = mention.mention_text.strip()
    ticker = text if text.isupper() and len(text) <= 6 else None
    isin = text if len(text) == 12 and text[:2].isalpha() and text[2:].isalnum() else None

    entity_id = await alias_repo.ticker_isin_match(ticker=ticker, isin=isin)
    audit.append(
        MentionResolution(
            mention_id=mention.mention_id,
            stage=2,
            score=CONFIDENCE_TICKER_ISIN if entity_id else 0.0,
            is_winner=entity_id is not None,
            candidate_entity_id=entity_id,
            metadata={"method": "ticker_isin", "ticker": ticker, "isin": isin},
        ),
    )
    if entity_id:
        return entity_id, CONFIDENCE_TICKER_ISIN
    return None, 0.0


async def _stage3_fuzzy(
    mention: EntityMention,
    alias_repo: EntityAliasRepository,
    audit: list[MentionResolution],
) -> tuple[UUID | None, float]:
    """Stage 3 — fuzzy trigram similarity via pg_trgm."""
    candidates = await alias_repo.fuzzy_trigram(mention.mention_text, threshold=0.75, top_k=5)

    if not candidates:
        audit.append(
            MentionResolution(
                mention_id=mention.mention_id,
                stage=3,
                score=0.0,
                is_winner=False,
                candidate_entity_id=None,
                metadata={"method": "fuzzy_trigram", "candidates": 0},
            ),
        )
        return None, 0.0

    best_entity_id, best_sim = candidates[0]
    composite = best_sim * FUZZY_CONFIDENCE_MULTIPLIER
    audit.append(
        MentionResolution(
            mention_id=mention.mention_id,
            stage=3,
            score=composite,
            is_winner=True,
            candidate_entity_id=best_entity_id,
            metadata={"method": "fuzzy_trigram", "similarity": best_sim, "candidates": len(candidates)},
        ),
    )
    return best_entity_id, composite


async def _stage4_ann(
    mention: EntityMention,
    embedding_repo: EntityProfileEmbeddingRepository,
    embedding_client: EmbeddingClient,
    model_id: str,
    instruction_prefix: str,
    audit: list[MentionResolution],
) -> tuple[UUID | None, float]:
    """Stage 4 — ANN HNSW on entity_embedding_state (view_type='definition')."""
    from ml_clients.dataclasses import EmbeddingInput  # type: ignore[import-not-found]

    # Embed the mention text
    try:
        inp = EmbeddingInput(
            text=mention.mention_text,
            model_id=model_id,
            instruction_prefix=instruction_prefix,
        )
        outputs = await embedding_client.embed([inp])
        query_vec = outputs[0].embedding if outputs else None
    except Exception:
        audit.append(
            MentionResolution(
                mention_id=mention.mention_id,
                stage=4,
                score=0.0,
                is_winner=False,
                candidate_entity_id=None,
                metadata={"method": "ann_hnsw", "error": "embedding_failed"},
            ),
        )
        return None, 0.0

    if query_vec is None:
        audit.append(
            MentionResolution(
                mention_id=mention.mention_id,
                stage=4,
                score=0.0,
                is_winner=False,
                candidate_entity_id=None,
                metadata={"method": "ann_hnsw", "error": "no_embedding"},
            ),
        )
        return None, 0.0

    candidates = await embedding_repo.ann_search(
        query_vec,
        view_type="definition",
        max_distance=ANN_MAX_DISTANCE,
        top_k=5,
    )

    if not candidates:
        audit.append(
            MentionResolution(
                mention_id=mention.mention_id,
                stage=4,
                score=0.0,
                is_winner=False,
                candidate_entity_id=None,
                metadata={"method": "ann_hnsw", "candidates": 0},
            ),
        )
        return None, 0.0

    best_entity_id, best_dist = candidates[0]
    composite = (1.0 - best_dist) * ANN_CONFIDENCE_MULTIPLIER

    # Require a clear margin between top-1 and top-2 to avoid ambiguity
    if len(candidates) >= 2:
        _, second_dist = candidates[1]
        margin = second_dist - best_dist
        if margin < ANN_CLEAR_MARGIN:
            audit.append(
                MentionResolution(
                    mention_id=mention.mention_id,
                    stage=4,
                    score=composite,
                    is_winner=False,
                    candidate_entity_id=best_entity_id,
                    metadata={"method": "ann_hnsw", "margin": margin, "rejected": "insufficient_margin"},
                ),
            )
            return None, composite

    audit.append(
        MentionResolution(
            mention_id=mention.mention_id,
            stage=4,
            score=composite,
            is_winner=True,
            candidate_entity_id=best_entity_id,
            metadata={"method": "ann_hnsw", "distance": best_dist},
        ),
    )
    return best_entity_id, composite


# ── Provisional queue insert ──────────────────────────────────────────────────

_PROVISIONAL_INSERT_SQL = """
INSERT INTO provisional_entity_queue
    (queue_id, normalized_surface, mention_class, mention_id, doc_id, created_at)
VALUES
    (:queue_id, lower(trim(:surface)), :mention_class, :mention_id, :doc_id, now())
ON CONFLICT (normalized_surface, mention_class) DO NOTHING
"""


async def _insert_provisional(
    mention: EntityMention,
    intelligence_session: object,
) -> None:
    """Insert a PROVISIONAL mention into the provisional_entity_queue."""
    from sqlalchemy import text  # type: ignore[import-untyped]

    await intelligence_session.execute(  # type: ignore[attr-defined]
        text(_PROVISIONAL_INSERT_SQL),
        {
            "queue_id": str(common.ids.new_uuid7()),
            "surface": mention.mention_text,
            "mention_class": str(mention.mention_class),
            "mention_id": str(mention.mention_id),
            "doc_id": str(mention.doc_id),
        },
    )


# ── Main block entry point ────────────────────────────────────────────────────


async def run_entity_resolution_block(
    mentions: list[EntityMention],
    *,
    alias_repo: EntityAliasRepository,
    embedding_repo: EntityProfileEmbeddingRepository,
    canonical_entity_repo: CanonicalEntityRepository,
    resolution_audit_repo: MentionResolutionRepository,
    embedding_client: EmbeddingClient,
    intelligence_session: object,
    model_id: str,
    instruction_prefix: str,
) -> tuple[list[EntityMention], list[MentionResolution]]:
    """Run the 4-stage entity resolution cascade for all mentions.

    Critical invariants (PRD §6.7 Block 9):
      - UNRESOLVED mentions are NEVER discarded — they remain in the output list.
      - AUTO_RESOLVE and PROVISIONAL outcomes write audit trail entries.
      - Provisional mentions are queued in provisional_entity_queue (UNIQUE guard).

    Args:
        mentions: All EntityMention objects from Block 4.
        alias_repo: Stage 1+2+3 queries against intelligence_db.entity_aliases.
        embedding_repo: Stage 4 ANN search.
        canonical_entity_repo: Entity lookup (unused in cascade but available).
        resolution_audit_repo: Writes MentionResolution audit rows.
        embedding_client: For Stage 4 mention text embedding.
        intelligence_session: Raw AsyncSession for provisional_entity_queue insert.
        model_id: Embedding model ID.
        instruction_prefix: Embedding instruction prefix.

    Returns:
        (resolved_mentions, audit_records)
        All input mentions are returned (potentially with resolved_entity_id set).
    """
    all_audit: list[MentionResolution] = []

    for mention in mentions:
        audit: list[MentionResolution] = []
        resolved_id: UUID | None = None
        confidence: float = 0.0

        # ── Stage 1: Exact alias ───────────────────────────────────────────
        resolved_id, confidence = await _stage1_exact(mention, alias_repo, audit)

        # ── Stage 2: Ticker/ISIN ───────────────────────────────────────────
        if resolved_id is None:
            resolved_id, confidence = await _stage2_ticker_isin(mention, alias_repo, audit)

        # ── Stage 3: Fuzzy trigram ─────────────────────────────────────────
        if resolved_id is None:
            resolved_id, confidence = await _stage3_fuzzy(mention, alias_repo, audit)

        # ── Stage 4: ANN HNSW ─────────────────────────────────────────────
        if resolved_id is None:
            resolved_id, confidence = await _stage4_ann(
                mention,
                embedding_repo=embedding_repo,
                embedding_client=embedding_client,
                model_id=model_id,
                instruction_prefix=instruction_prefix,
                audit=audit,
            )

        # ── Resolution classification ──────────────────────────────────────
        if resolved_id is not None and confidence >= AUTO_RESOLVE_THRESHOLD:
            mention.resolved_entity_id = resolved_id
            mention.resolution_confidence = confidence
            mention.resolution_stage = audit[-1].stage if audit else None
            mention.resolution_outcome = ResolutionOutcome.AUTO_RESOLVED

        elif resolved_id is not None and confidence >= PROVISIONAL_THRESHOLD:
            # Provisional — queue for human/deferred resolution
            mention.resolution_confidence = confidence
            mention.resolution_outcome = ResolutionOutcome.PROVISIONAL
            try:
                await _insert_provisional(mention, intelligence_session)
            except Exception:
                logger.warning(
                    "entity_resolution.provisional_insert_failed",
                    mention_id=str(mention.mention_id),
                )

        else:
            # UNRESOLVED — preserve mention, never discard
            mention.resolution_outcome = ResolutionOutcome.UNRESOLVED
            logger.debug(
                "entity_resolution.unresolved",
                mention_id=str(mention.mention_id),
                text=mention.mention_text,
            )

        all_audit.extend(audit)

    return mentions, all_audit
