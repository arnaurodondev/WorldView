"""Worker 13B: Contradiction batch detection (PRD §6.7 Block 13B).

Runs every 30 minutes.  Full subject-based scan of non-neutral claims within
the 90-day window, using ``idx_claims_contradiction_detection`` index.
Same subject-based logic as Block 12b (hot path) but batch-oriented.

Rate-limited by LIMIT in the query — processes at most 500 claims per run.

T-B-02 (PLAN-0074 Wave B): After inserting contradiction links, aggregate
per-relation contra columns on the ``relations`` table:
  - ``strongest_contra_score`` (MAX contradiction strength)
  - ``contra_count_by_type`` (JSONB ``{relation_type: count}``)
  - ``latest_contra_at`` (MAX detected_at)

Invalidation branch: when a relation's recomputed confidence drops below 0.1
the relation is soft-closed (``valid_to = NOW()``) in the same transaction.
No Kafka event is emitted — deferred to a follow-up plan per design note.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from common.time import utc_now  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]

_BATCH_LIMIT = 500
_CONTRADICTION_WINDOW_DAYS = 90

# Relations whose new confidence falls below this threshold are soft-closed
# (valid_to = NOW()) in the same transaction.  No Kafka event is emitted —
# deferred to a follow-up plan.
_INVALIDATION_CONFIDENCE_THRESHOLD = 0.1


class ContradictionBatchWorker:
    """Batch contradiction detection scan (Worker 13B).

    Args:
    ----
        session_factory: Read/write sessionmaker for intelligence_db.

    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def run(self) -> None:
        """Scan claims, insert contradiction links, and refresh per-relation contra columns."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.contradiction import (
            ContradictionRepository,
        )
        from knowledge_graph.infrastructure.intelligence_db.repositories.relation import (
            RelationRepository,
        )

        links_inserted = 0
        relations_updated = 0
        relations_invalidated = 0

        async with self._sf() as session:
            contra_repo = ContradictionRepository(session)
            rel_repo = RelationRepository(session)

            # Fetch a batch of non-neutral claims to examine
            candidates = await contra_repo.fetch_claims_for_batch_scan(  # type: ignore[attr-defined]
                limit=_BATCH_LIMIT,
                window_days=_CONTRADICTION_WINDOW_DAYS,
            )

            for claim in candidates:
                claim_id = claim["claim_id"]  # type: ignore[assignment]
                subject_id = claim["subject_entity_id"]  # type: ignore[assignment]
                claim_type = str(claim["claim_type"])
                polarity = str(claim["polarity"])
                confidence = float(claim["extraction_confidence"])  # type: ignore[arg-type]

                # Find opposing claims for this subject/type
                opposing = await contra_repo.find_opposing_claims(
                    subject_id,  # type: ignore[arg-type]
                    claim_type,
                    polarity,
                    window_days=_CONTRADICTION_WINDOW_DAYS,
                )

                for opp in opposing:
                    opp_claim_id = opp["claim_id"]  # type: ignore[assignment]
                    opp_confidence = float(opp["extraction_confidence"])  # type: ignore[arg-type]
                    strength = min(confidence, opp_confidence)

                    now = utc_now()  # type: ignore[no-any-return]
                    # insert_link uses ON CONFLICT DO NOTHING — idempotent.
                    # COLUMN-NAMING DEBT (2026-06-16 data-pipeline-gaps Gap 1):
                    # the ``relation_evidence_id`` column is named like a
                    # ``relation_evidence_raw.raw_id`` FK, but we deliberately
                    # store the SUBJECT claim's ``claims.claim_id`` here (there
                    # is no FK constraint). Every read path resolves the subject
                    # by joining ``claims`` on this value, so write & read stay
                    # in sync. A rename/clarification migration is recommended
                    # (see fix report) but out of scope for the read-side fix.
                    await contra_repo.insert_link(
                        relation_evidence_id=claim_id,  # type: ignore[arg-type]
                        claim_id=opp_claim_id,  # type: ignore[arg-type]
                        contradiction_type="polarity_conflict",
                        strength=strength,
                        detected_at=now,
                    )
                    links_inserted += 1

            # ------------------------------------------------------------------
            # T-B-02: Aggregate contradiction stats and update relations table.
            # Run once per cycle after all link insertions to amortise cost.
            # ------------------------------------------------------------------
            if links_inserted > 0:
                # Fetch all affected (relation_id, stats) from the DB, aggregated.
                relation_stats = await contra_repo.aggregate_contra_stats_for_active_links()  # type: ignore[attr-defined]

                for stat in relation_stats:
                    relation_id = stat["relation_id"]
                    strongest = float(stat["strongest_contra_score"])  # type: ignore[arg-type]
                    count_by_type: dict[str, object] = dict(stat["contra_count_by_type"])  # type: ignore[arg-type, call-overload]
                    latest_at = stat["latest_contra_at"]
                    new_confidence: float | None = (
                        float(stat["current_confidence"])  # type: ignore[arg-type]
                        if stat.get("current_confidence") is not None
                        else None
                    )

                    await rel_repo.update_contra_columns(  # type: ignore[attr-defined]
                        relation_id=relation_id,  # type: ignore[arg-type]
                        strongest_contra_score=strongest,
                        contra_count_by_type=count_by_type,
                        latest_contra_at=latest_at,
                    )
                    relations_updated += 1

                    # Invalidation branch: soft-close the relation if confidence
                    # has dropped below the threshold (T-B-02 invalidation).
                    # Per design: no Kafka event emitted here — deferred.
                    if new_confidence is not None and new_confidence < _INVALIDATION_CONFIDENCE_THRESHOLD:
                        now = utc_now()  # type: ignore[no-any-return]
                        await rel_repo.invalidate_relation(  # type: ignore[attr-defined]
                            relation_id=relation_id,  # type: ignore[arg-type]
                            valid_to=now,
                            valid_to_confidence=new_confidence,
                            valid_to_source="contradiction_batch_worker",
                        )
                        logger.info(  # type: ignore[no-any-return]
                            "contradiction_worker_relation_invalidated",
                            relation_id=str(relation_id),
                            confidence=new_confidence,
                        )
                        relations_invalidated += 1

            await session.commit()

        logger.info(  # type: ignore[no-any-return]
            "contradiction_batch_worker_complete",
            links_inserted=links_inserted,
            relations_updated=relations_updated,
            relations_invalidated=relations_invalidated,
        )
