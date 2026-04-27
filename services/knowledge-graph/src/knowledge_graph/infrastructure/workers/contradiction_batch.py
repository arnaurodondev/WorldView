"""Worker 13B: Contradiction batch detection (PRD §6.7 Block 13B).

Runs every 30 minutes.  Full subject-based scan of non-neutral claims within
the 90-day window, using ``idx_claims_contradiction_detection`` index.
Same subject-based logic as Block 12b (hot path) but batch-oriented.

Rate-limited by LIMIT in the query — processes at most 500 claims per run.
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


class ContradictionBatchWorker:
    """Batch contradiction detection scan (Worker 13B).

    Args:
    ----
        session_factory: Read/write sessionmaker for intelligence_db.

    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def run(self) -> None:
        """Scan claims and insert missing contradiction links."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.contradiction import (
            ContradictionRepository,
        )

        links_inserted = 0
        async with self._sf() as session:
            contra_repo = ContradictionRepository(session)

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
                    # insert_link uses ON CONFLICT DO NOTHING — idempotent
                    await contra_repo.insert_link(
                        relation_evidence_id=claim_id,  # type: ignore[arg-type]
                        claim_id=opp_claim_id,  # type: ignore[arg-type]
                        contradiction_type="polarity_conflict",
                        strength=strength,
                        detected_at=now,
                    )
                    links_inserted += 1

            await session.commit()

        logger.info(  # type: ignore[no-any-return]
            "contradiction_batch_worker_complete",
            links_inserted=links_inserted,
        )
