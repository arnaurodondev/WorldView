"""Worker 13A: Confidence recomputation (PRD §6.7 Block 13A).

Runs every 15 minutes (configurable).  Processes ``relation_evidence_raw``
rows that are unprocessed (``processed=false, entity_provisional=false``),
grouped by hash partition (0-7) to distribute lock contention.

For each partition batch:
  1. Fetch unprocessed raw evidence rows (FOR UPDATE SKIP LOCKED).
  2. Group by (subject, object, canonical_type) → find the relation.
  3. Fetch ALL raw evidence for that triple to compute a full confidence score.
  4. Fetch active contradiction links for the subject entity.
  5. Apply 4-step confidence formula (``domain/confidence.py``).
  6. Persist updated confidence and mark raw rows as processed.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.domain.confidence import ContradictionInput, EvidenceInput, compute_confidence
from knowledge_graph.domain.enums import SemanticMode
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.config import Settings

logger = get_logger(__name__)  # type: ignore[no-any-return]

_NUM_PARTITIONS = 8
_PARTITION_BATCH_SIZE = 500


class ConfidenceWorker:
    """Recomputes confidence for all stale relations (Worker 13A).

    Args:
    ----
        session_factory: Read/write sessionmaker for intelligence_db.
        settings:        Service settings (formula constants).

    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._sf = session_factory
        self._settings = settings

    async def run(self) -> None:
        """Process all 8 partitions, recomputing stale confidence scores."""
        total_updated = 0
        total_evidence_rows = 0
        empty_partitions = 0

        for partition_key in range(_NUM_PARTITIONS):
            updated, evidence_rows = await self._process_partition(partition_key)
            total_updated += updated
            total_evidence_rows += evidence_rows
            if evidence_rows == 0:
                empty_partitions += 1

        logger.info(  # type: ignore[no-any-return]
            "confidence_worker_complete",
            relations_updated=total_updated,
            evidence_rows_processed=total_evidence_rows,
            empty_partitions=empty_partitions,
            partitions_total=_NUM_PARTITIONS,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _process_partition(self, partition_key: int) -> tuple[int, int]:
        from knowledge_graph.infrastructure.intelligence_db.repositories.contradiction import (
            ContradictionRepository,
        )
        from knowledge_graph.infrastructure.intelligence_db.repositories.relation import RelationRepository
        from knowledge_graph.infrastructure.intelligence_db.repositories.relation_evidence import (
            RelationEvidenceRepository,
        )

        async with self._sf() as session:
            rel_repo = RelationRepository(session)
            ev_repo = RelationEvidenceRepository(session)
            contra_repo = ContradictionRepository(session)

            # Fetch unprocessed rows for this partition
            unprocessed = await ev_repo.fetch_unprocessed_by_partition(partition_key, _PARTITION_BATCH_SIZE)
            row_count = len(unprocessed)
            if not unprocessed:
                logger.debug(  # type: ignore[no-any-return]
                    "confidence_worker_partition_empty",
                    partition_key=partition_key,
                    message="no unprocessed evidence rows — may indicate data gap or fully caught-up partition",
                )
                return 0, 0

            logger.debug(  # type: ignore[no-any-return]
                "confidence_worker_partition_start",
                partition_key=partition_key,
                unprocessed_rows=row_count,
            )

            # Group by triple to find unique relations to update
            triple_to_rows: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
            for row in unprocessed:
                key = (
                    str(row["subject_entity_id"]),
                    str(row["object_entity_id"]),
                    str(row["canonical_type"]),
                )
                triple_to_rows[key].append(row)

            updated = 0
            all_raw_ids: list[UUID] = []

            for (subject_str, object_str, ctype), _ in triple_to_rows.items():
                subject_id = UUID(subject_str)
                object_id = UUID(object_str)

                # Fetch relation metadata
                rel_row = await rel_repo.get(subject_id, ctype, object_id)
                if rel_row is None:
                    continue

                relation_id = rel_row["relation_id"]  # type: ignore[assignment]
                decay_alpha = float(rel_row["decay_alpha"])  # type: ignore[arg-type]
                semantic_mode = SemanticMode(str(rel_row["semantic_mode"]))

                # All raw evidence for this triple (processed + unprocessed)
                all_ev = await ev_repo.get_all_raw_for_triple(subject_id, object_id, ctype)  # type: ignore[attr-defined]
                if not all_ev:
                    continue

                evidence_inputs = [
                    EvidenceInput(
                        source_weight=float(e["source_trust_weight"]),  # type: ignore[arg-type]
                        source_type="unknown",
                        source_name="unknown",
                        evidence_date=e["evidence_date"],  # type: ignore[arg-type]
                    )
                    for e in all_ev
                ]

                contra_rows = await contra_repo.fetch_active_for_subject(subject_id)
                contradiction_inputs = [
                    ContradictionInput(
                        strength=float(c["strength"]),  # type: ignore[arg-type]
                        detected_at=c["detected_at"],  # type: ignore[arg-type]
                    )
                    for c in contra_rows
                ]

                s = self._settings
                components = compute_confidence(
                    evidence_inputs,
                    contradiction_inputs,
                    decay_alpha,
                    semantic_mode,
                    corroboration_cap=s.confidence_corroboration_cap,
                    contradiction_cap=s.confidence_contradiction_cap,
                    temporal_claim_alpha=s.confidence_temporal_claim_alpha,
                    corroboration_gain_per_source=s.confidence_corroboration_gain_per_source,
                    corroboration_min_temporal_weight=s.confidence_corroboration_min_temporal_weight,
                    contradiction_top_k=s.confidence_contradiction_top_k,
                )

                await rel_repo.mark_confidence_updated(
                    relation_id,  # type: ignore[arg-type]
                    components.final,
                    utc_now(),  # type: ignore[no-any-return]
                )

                # T-B-01: populate valid_from + relation_period_type from
                # earliest evidence date in same transaction as confidence update.
                valid_from = await ev_repo.get_earliest_evidence_date(  # type: ignore[attr-defined]
                    subject_id, object_id, ctype
                )
                if valid_from is not None:
                    # Derive period type from valid_to on the relation row.
                    # rel_row comes from get() which does not include valid_to;
                    # fetch it now with a lightweight supplementary query.
                    valid_to = await rel_repo.get_valid_to(relation_id)  # type: ignore[arg-type, attr-defined]
                    relation_period_type = _derive_period_type(valid_from, valid_to)
                    await rel_repo.update_valid_from_and_period_type(  # type: ignore[attr-defined]
                        relation_id,  # type: ignore[arg-type]
                        valid_from,
                        relation_period_type,
                    )

                all_raw_ids.extend(UUID(str(r["raw_id"])) for r in _)  # type: ignore[misc]
                updated += 1

            # Mark the entire partition batch as processed
            if all_raw_ids:
                await ev_repo.mark_processed(all_raw_ids, utc_now())  # type: ignore[no-any-return]

            await session.commit()

            if updated == 0:
                logger.warning(  # type: ignore[no-any-return]
                    "confidence_worker_partition_zero_updates",
                    partition_key=partition_key,
                    unprocessed_rows=row_count,
                    message="unprocessed rows found but 0 relations updated — possible relation lookup misses",
                )
            else:
                logger.debug(  # type: ignore[no-any-return]
                    "confidence_worker_partition_complete",
                    partition_key=partition_key,
                    relations_updated=updated,
                    evidence_rows=row_count,
                )

        return updated, row_count


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _derive_period_type(
    valid_from: object,
    valid_to: object | None,
) -> str:
    """Derive ``relation_period_type`` from valid_from / valid_to timestamps.

    Rules (T-B-01):
    - ``valid_to IS NOT NULL AND (valid_to - valid_from) < 7 days`` → POINT_IN_TIME
    - ``valid_to IS NOT NULL``                                        → HISTORICAL
    - ``valid_to IS NULL``                                            → ONGOING
    """
    if valid_to is None:
        return "ONGOING"
    try:
        delta: timedelta = valid_to - valid_from  # type: ignore[operator]
        if delta < timedelta(days=7):
            return "POINT_IN_TIME"
    except TypeError:
        # Unexpected types — fall back to HISTORICAL
        pass
    return "HISTORICAL"
