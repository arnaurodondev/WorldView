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
from knowledge_graph.domain.calibration import BetaCalibrator
from knowledge_graph.domain.confidence import (
    ContradictionInput,
    EvidenceInput,
    compute_confidence,
    compute_confidence_beta,
)
from knowledge_graph.domain.enums import SemanticMode
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.config import Settings
    from knowledge_graph.infrastructure.intelligence_db.repositories.contradiction import (
        ContradictionRepository,
    )
    from knowledge_graph.infrastructure.intelligence_db.repositories.relation import RelationRepository
    from knowledge_graph.infrastructure.intelligence_db.repositories.relation_evidence import (
        RelationEvidenceRepository,
    )

logger = get_logger(__name__)  # type: ignore[no-any-return]

_NUM_PARTITIONS = 8
_PARTITION_BATCH_SIZE = 500
# PLAN-0109 W2: per-partition cap for the time-driven staleness sweep.
_SWEEP_BATCH_SIZE = 500
# PLAN-0109 W4: minimum normalised-text length to form a syndication key.
_SYNDICATION_MIN_LEN = 20


def _syndication_key(evidence_text: object) -> str | None:
    """Syndication-cluster key for one evidence piece (PLAN-0109 W4).

    A hash of the normalised evidence text: reprints of the same wire story
    (identical text republished by many outlets) share a key and count once in
    the confidence mass. Returns ``None`` for empty/trivial text (treated as an
    independent source). Self-contained — the S5 MinHash clusters live in
    content_store_db and are off-limits cross-service (R9).
    """
    if not isinstance(evidence_text, str):
        return None
    norm = " ".join(evidence_text.lower().split())
    if len(norm) < _SYNDICATION_MIN_LEN:
        return None
    import hashlib

    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


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
        # Populated at the start of run(); safe defaults so direct method calls
        # (and tests) work without a full run().
        self._source_trust: dict[str, float] = {}
        self._calibrator: BetaCalibrator | None = None

    async def run(self) -> None:
        """Recompute confidence for all 8 partitions.

        Two passes per partition: (1) the evidence-driven pass recomputes
        relations that received new evidence; (2) the PLAN-0109 W2 staleness
        sweep recomputes relations due by their decay-class cadence, so
        confidence decays over wall-clock time and the corpus migrates to v2.
        """
        total_updated = 0
        total_evidence_rows = 0
        total_swept = 0
        empty_partitions = 0

        # PLAN-0109 W1: load the graded source-trust map once per run so the v2
        # backbone can weight evidence by source_type (the table was never JOINed
        # before — per-evidence trust was effectively a constant 0.9/1.0). Only
        # loaded when v2 is active; the v1 path does not use it.
        self._source_trust = await self._load_source_trust() if self._settings.confidence_formula_v2 else {}
        # PLAN-0109 W6: build the Beta calibrator once; None when it is the identity
        # map so raw scores pass through exactly (calibration is a no-op until fitted).
        _cal = BetaCalibrator(
            a=self._settings.confidence_calibration_a,
            b=self._settings.confidence_calibration_b,
            c=self._settings.confidence_calibration_c,
        )
        self._calibrator = None if _cal.is_identity else _cal

        for partition_key in range(_NUM_PARTITIONS):
            updated, evidence_rows = await self._process_partition(partition_key)
            total_updated += updated
            total_evidence_rows += evidence_rows
            if evidence_rows == 0:
                empty_partitions += 1
            total_swept += await self._sweep_partition(partition_key)

        logger.info(  # type: ignore[no-any-return]
            "confidence_worker_complete",
            relations_updated=total_updated,
            relations_swept=total_swept,
            evidence_rows_processed=total_evidence_rows,
            empty_partitions=empty_partitions,
            partitions_total=_NUM_PARTITIONS,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _load_source_trust(self) -> dict[str, float]:
        """Load ``{source_type: trust_weight}`` from ``source_trust_weights`` (PLAN-0109 W1)."""
        from sqlalchemy import text as _sa_text

        async with self._sf() as session:
            result = await session.execute(_sa_text("SELECT source_type, trust_weight FROM source_trust_weights"))
            return {str(row[0]): float(row[1]) for row in result.fetchall()}

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

            for (subject_str, object_str, ctype), rows in triple_to_rows.items():
                subject_id = UUID(subject_str)
                object_id = UUID(object_str)

                rel_row = await rel_repo.get(subject_id, ctype, object_id)
                if rel_row is None:
                    continue

                did_update = await self._recompute_relation(
                    rel_repo,
                    ev_repo,
                    contra_repo,
                    relation_id=rel_row["relation_id"],  # type: ignore[arg-type]
                    subject_id=subject_id,
                    object_id=object_id,
                    ctype=ctype,
                    semantic_mode=SemanticMode(str(rel_row["semantic_mode"])),
                    decay_alpha=float(rel_row["decay_alpha"]),  # type: ignore[arg-type]
                    base_confidence=float(rel_row["base_confidence"]),  # type: ignore[arg-type]
                )
                if did_update:
                    all_raw_ids.extend(UUID(str(r["raw_id"])) for r in rows)  # type: ignore[misc]
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

    async def _recompute_relation(
        self,
        rel_repo: RelationRepository,
        ev_repo: RelationEvidenceRepository,
        contra_repo: ContradictionRepository,
        *,
        relation_id: UUID,
        subject_id: UUID,
        object_id: UUID,
        ctype: str,
        semantic_mode: SemanticMode,
        decay_alpha: float,
        base_confidence: float,
    ) -> bool:
        """Recompute + persist one relation's confidence.

        Returns ``False`` when the triple has no raw evidence (nothing to score).
        Shared by the evidence-driven path (``_process_partition``) and the
        time-driven staleness sweep (``_sweep_partition``) — PLAN-0109 W1/W2.
        """
        all_ev = await ev_repo.get_all_raw_for_triple(subject_id, object_id, ctype)  # type: ignore[attr-defined]
        if not all_ev:
            return False

        contra_rows = await contra_repo.fetch_active_for_subject(subject_id)
        contradiction_inputs = [
            ContradictionInput(
                strength=float(c["strength"]),  # type: ignore[arg-type]
                detected_at=c["detected_at"],  # type: ignore[arg-type]
            )
            for c in contra_rows
        ]

        # PLAN-0109 W3: valid_to drives step decay (a stateful fact expires after
        # its validity window) and is recorded in the bitemporal history. One
        # ``now`` is shared by the formula, the persist, and the history row.
        valid_to = await rel_repo.get_valid_to(relation_id)  # type: ignore[attr-defined]
        now = utc_now()

        s = self._settings
        if s.confidence_formula_v2:
            # PLAN-0109 W1: Beta / subjective-logic backbone — real source identity
            # (un-breaks corroboration), graded source trust, per-evidence extraction
            # confidence, and the predicate prior all enter the score.
            evidence_inputs = [
                EvidenceInput(
                    source_weight=self._source_trust.get(
                        str(e.get("source_type") or ""), s.confidence_default_source_trust
                    ),
                    source_type=str(e.get("source_type") or "unknown"),
                    source_name=str(e.get("source_name") or "unknown"),
                    evidence_date=e["evidence_date"],  # type: ignore[arg-type]
                    extraction_confidence=float(e["extraction_confidence"]),  # type: ignore[arg-type]
                    dedup_key=_syndication_key(e.get("evidence_text")),
                )
                for e in all_ev
            ]
            final_confidence = compute_confidence_beta(
                evidence_inputs,
                contradiction_inputs,
                decay_alpha,
                semantic_mode,
                base_confidence,
                prior_strength=s.confidence_prior_strength,
                signal_decay_floor=s.confidence_signal_decay_floor,
                valid_to=valid_to,
                now=now,
                calibrator=self._calibrator,
            ).final
        else:
            evidence_inputs = [
                EvidenceInput(
                    source_weight=float(e["source_trust_weight"]),  # type: ignore[arg-type]
                    source_type="unknown",
                    source_name="unknown",
                    evidence_date=e["evidence_date"],  # type: ignore[arg-type]
                )
                for e in all_ev
            ]
            final_confidence = compute_confidence(
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
            ).final

        await rel_repo.mark_confidence_updated(relation_id, final_confidence, now)

        # T-B-01: populate valid_from + relation_period_type from earliest evidence.
        valid_from = await ev_repo.get_earliest_evidence_date(subject_id, object_id, ctype)  # type: ignore[attr-defined]
        if valid_from is not None:
            await rel_repo.update_valid_from_and_period_type(  # type: ignore[attr-defined]
                relation_id,
                valid_from,
                _derive_period_type(valid_from, valid_to),
            )

        # PLAN-0109 W3: append a bitemporal version row (valid time + transaction
        # time) so the relation's confidence/validity history is reconstructable
        # ("what did we believe on date X").
        await rel_repo.append_relation_history(  # type: ignore[attr-defined]
            relation_id=relation_id,
            subject_entity_id=subject_id,
            object_entity_id=object_id,
            canonical_type=ctype,
            confidence=final_confidence,
            valid_from=valid_from,
            valid_to=valid_to,
            decay_class=None,
            recorded_at=now,
        )
        return True

    async def _sweep_partition(self, partition_key: int) -> int:
        """Time-driven staleness sweep (PLAN-0109 W2).

        Recompute relations that are DUE by their decay-class cadence
        (``decay_class_config.recompute_interval_minutes``), independent of new
        evidence arriving — this is what makes confidence decay over wall-clock
        time and migrates the existing corpus to the v2 model.
        """
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

            due = await rel_repo.fetch_due_for_recompute(partition_key, _SWEEP_BATCH_SIZE)  # type: ignore[attr-defined]
            updated = 0
            for d in due:
                did = await self._recompute_relation(
                    rel_repo,
                    ev_repo,
                    contra_repo,
                    relation_id=d["relation_id"],  # type: ignore[arg-type]
                    subject_id=d["subject_entity_id"],  # type: ignore[arg-type]
                    object_id=d["object_entity_id"],  # type: ignore[arg-type]
                    ctype=str(d["canonical_type"]),
                    semantic_mode=SemanticMode(str(d["semantic_mode"])),
                    decay_alpha=float(d["decay_alpha"]),  # type: ignore[arg-type]
                    base_confidence=float(d["base_confidence"]),  # type: ignore[arg-type]
                )
                if did:
                    updated += 1
            await session.commit()
            return updated


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
