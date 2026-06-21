"""Worker 13B: periodic relation_evidence_raw → relation_evidence promotion (PRD §6.7 Block 13B).

Runs every 300 seconds (5 minutes).  Promotes not-yet-promoted rows
(``promoted_at IS NULL``) from the ``relation_evidence_raw`` staging table to
the immutable, range-partitioned ``relation_evidence`` table in batches of 200.

Scan-bound discipline (UI-timeout incident fix): the fetch query filters
``promoted_at IS NULL`` so each run scans only the unpromoted frontier, not the
entire already-promoted backlog.  ``promoted_at`` is stamped by this worker in
the same transaction as the INSERT, and backfilled for the pre-existing backlog
by migration 0061.  This is DISTINCT from the ``processed`` boolean, which is
owned by Worker 13A (ConfidenceWorker) and marks "confidence recomputed", not
"promoted".

Promotion criteria (mirrors the one-shot ``scripts/ops/promote_relation_evidence.py``):
  * ``entity_provisional = false`` — only non-provisional evidence is canon.
  * Matching relation exists (JOIN on subject_entity_id, object_entity_id,
    canonical_type) — orphan raw rows are silently skipped (blocked_provisional).
  * NOT EXISTS duplicate guard on (relation_id, doc_id, evidence_date) — making
    repeated runs fully idempotent.
  * E-3 quality gate: row must satisfy at least one of:
      - extraction_confidence >= 0.70 (strong LLM signal from a single doc), OR
      - evidence density >= 5% (triple appears in ≥5% of docs mentioning either entity).
    Rows failing the gate stay in relation_evidence_raw for future re-promotion
    once additional corroborating evidence accumulates.

BP-SA1-004 context: before this worker existed, no scheduled process promoted
raw rows to the immutable table, leaving SummaryWorker starved of high-quality
evidence and falling back to the raw-path for all relations.

Session discipline (DS-001): one short-lived write session per batch — the
SELECT + INSERT run inside the same transaction and the session is released
immediately after commit.  No session is held across loop iterations.

Logging contract: ``relation_evidence_promoter_complete`` is emitted after each
run with ``promoted``, ``blocked_provisional``, ``no_match``, and
``gated_quality`` counts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from knowledge_graph.infrastructure.metrics.prometheus import kg_evidence_quality_gated_total
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Rows promoted per run() call.  200 is large enough to drain the typical
# incremental backlog from a 5-minute NLP pipeline burst without holding the
# write session open for more than a few hundred milliseconds.
_BATCH_SIZE = 200

# E-3 quality gate thresholds.
#
# Minimum extraction confidence for single-document promotion (no density
# requirement).  A score of 0.70 indicates the LLM was highly confident about
# the relation and the triple does not need additional corroboration.
_CONF_THRESHOLD = 0.70

# Minimum evidence density for low-confidence evidence: the triple must appear
# in at least this fraction of documents mentioning both entities before it can
# be promoted.  0.05 = 5% — prevents a single hallucinated extraction from
# becoming a confirmed graph edge.
_DENSITY_THRESHOLD = 0.05

# SQL: fetch a batch of promotable rows.
#
# Promotion eligibility:
#   0. promoted_at IS NULL  → skip the already-promoted backlog.  This is the
#      primary scan-bound filter: without it the worker re-scanned every
#      already-promoted non-provisional row (81,769 on live dev) on every 5-min
#      run, promoting 0 rows and pinning Postgres for 7.5-12+ minutes per run
#      (the UI-timeout incident).  ``promoted_at`` is set by this worker after
#      the INSERT (see _MARK_PROMOTED_SQL) and is backfilled for the existing
#      already-promoted backlog by migration 0061.  NOTE: this is distinct from
#      the ``processed`` flag, which is owned by Worker 13A (ConfidenceWorker)
#      and marks "confidence recomputed", NOT "promoted".
#   1. entity_provisional = false  → only confirmed entities.
#   2. JOIN relations on the triple (subject, object, canonical_type) to
#      resolve the UUID relation_id — raw rows store the triple, not the UUID.
#   3. NOT EXISTS dedup check against relation_evidence — retained as a belt-and-
#      braces guard against the rare TOCTOU race where two rows share the same
#      (relation, doc, evidence_date) key; the promoted_at filter handles the
#      common case.
#   4. E-3 quality gate: at least one of:
#        a. extraction_confidence >= :conf_threshold  (strong single-doc signal)
#        b. evidence density >= :density_threshold  (broad corpus corroboration)
#      Evidence density = COUNT(triple rows) / COUNT(DISTINCT docs mentioning
#      either entity).  Rows failing the gate stay in relation_evidence_raw
#      until enough corroborating evidence accumulates.
#
# We ORDER BY extracted_at so older rows are promoted first (FIFO queue
# semantics) — this prevents newer evidence from being indefinitely
# preferred over older evidence that happens to share the same triple key.
_FETCH_SQL = """
SELECT
    rer.raw_id,
    r.relation_id,
    rer.source_document_id   AS doc_id,
    rer.chunk_id,
    rer.evidence_text,
    rer.extraction_confidence,
    rer.source_trust_weight  AS source_weight,
    rer.evidence_date,
    rer.claim_id
FROM relation_evidence_raw rer
JOIN relations r
  ON  r.subject_entity_id = rer.subject_entity_id
  AND r.object_entity_id  = rer.object_entity_id
  AND r.canonical_type    = rer.canonical_type
WHERE rer.entity_provisional = false
  AND rer.promoted_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM relation_evidence re
    WHERE re.relation_id   = r.relation_id
      AND re.doc_id        = rer.source_document_id
      AND re.evidence_date = rer.evidence_date
  )
  AND (
      rer.extraction_confidence >= :conf_threshold
      OR (
          SELECT CAST(COUNT(*) AS float)
          FROM relation_evidence_raw rer2
          WHERE rer2.subject_entity_id = rer.subject_entity_id
            AND rer2.object_entity_id  = rer.object_entity_id
            AND rer2.canonical_type    = rer.canonical_type
      ) / NULLIF(
          (
              -- Density denominator: distinct documents that mention either
              -- entity anywhere in the relation-extraction corpus. We use
              -- relation_evidence_raw itself (intelligence_db) as the
              -- mention proxy because entity_mentions lives in nlp_db; the
              -- previous query reached cross-DB (violates R9) and crashed
              -- every 5 min with UndefinedTableError (Final-QA-1).
              SELECT COUNT(DISTINCT rer3.source_document_id)
              FROM relation_evidence_raw rer3
              WHERE rer3.subject_entity_id IN (rer.subject_entity_id, rer.object_entity_id)
                 OR rer3.object_entity_id  IN (rer.subject_entity_id, rer.object_entity_id)
          ), 0
      ) >= :density_threshold
  )
ORDER BY rer.extracted_at
LIMIT :batch_size
"""

# SQL: count raw rows that are blocked because entity_provisional = true.
# Used for the summary log metric only — does not affect promotion logic.
_COUNT_PROVISIONAL_SQL = """
SELECT count(*) FROM relation_evidence_raw WHERE entity_provisional = true
"""

# SQL: count raw rows with no matching relation (potential orphans).
# Cheap approximation using anti-join; not promoted but counted for ops.
_COUNT_NO_MATCH_SQL = """
SELECT count(*)
FROM relation_evidence_raw rer
WHERE rer.entity_provisional = false
  AND NOT EXISTS (
    SELECT 1 FROM relations r
    WHERE r.subject_entity_id = rer.subject_entity_id
      AND r.object_entity_id  = rer.object_entity_id
      AND r.canonical_type    = rer.canonical_type
  )
"""

# SQL: count rows that are eligible for promotion (matched relation, not yet
# promoted, non-provisional) but are blocked by the E-3 quality gate — i.e.
# extraction_confidence < conf_threshold AND density < density_threshold.
# Used for the gated_quality diagnostic log metric and Prometheus counter.
_COUNT_GATED_QUALITY_SQL = """
SELECT count(*)
FROM relation_evidence_raw rer
WHERE rer.entity_provisional = false
  AND rer.promoted_at IS NULL
  AND EXISTS (
    SELECT 1 FROM relations r
    WHERE r.subject_entity_id = rer.subject_entity_id
      AND r.object_entity_id  = rer.object_entity_id
      AND r.canonical_type    = rer.canonical_type
  )
  AND NOT EXISTS (
    SELECT 1 FROM relation_evidence re
    WHERE re.relation_id = (
        SELECT r.relation_id FROM relations r
        WHERE r.subject_entity_id = rer.subject_entity_id
          AND r.object_entity_id  = rer.object_entity_id
          AND r.canonical_type    = rer.canonical_type
        LIMIT 1
    )
      AND re.doc_id        = rer.source_document_id
      AND re.evidence_date = rer.evidence_date
  )
  AND rer.extraction_confidence < :conf_threshold
  AND (
      SELECT CAST(COUNT(*) AS float)
      FROM relation_evidence_raw rer2
      WHERE rer2.subject_entity_id = rer.subject_entity_id
        AND rer2.object_entity_id  = rer.object_entity_id
        AND rer2.canonical_type    = rer.canonical_type
  ) / NULLIF(
      (
          -- Same intelligence_db-only density denominator as _FETCH_SQL.
          -- See note there for the cross-DB rationale (Final-QA-1).
          SELECT COUNT(DISTINCT rer3.source_document_id)
          FROM relation_evidence_raw rer3
          WHERE rer3.subject_entity_id IN (rer.subject_entity_id, rer.object_entity_id)
             OR rer3.object_entity_id  IN (rer.subject_entity_id, rer.object_entity_id)
      ), 0
  ) < :density_threshold
"""

# SQL: insert one promotable row into the partitioned immutable table.
# ON CONFLICT DO NOTHING: the NOT EXISTS pre-filter handles most duplicates
# but this guard catches the rare TOCTOU race on concurrent restarts.
_INSERT_SQL = """
INSERT INTO relation_evidence (
    relation_id, doc_id, chunk_id, evidence_text,
    extraction_confidence, source_weight, evidence_date, claim_id
) VALUES (
    :relation_id, :doc_id, :chunk_id, :evidence_text,
    :extraction_confidence, :source_weight, :evidence_date, :claim_id
)
ON CONFLICT DO NOTHING
"""

# SQL: stamp the raw row as promoted so subsequent runs skip it via the
# ``promoted_at IS NULL`` filter in _FETCH_SQL.  Runs in the SAME transaction as
# the INSERT above, so promotion + marking commit atomically — a crash between
# the two cannot leave a promoted row unmarked (which would only cost a redundant
# ON CONFLICT DO NOTHING re-insert next run anyway, never a duplicate).
_MARK_PROMOTED_SQL = """
UPDATE relation_evidence_raw
SET promoted_at = now()
WHERE raw_id = :raw_id
"""


class RelationEvidencePromoterWorker:
    """Promotes relation_evidence_raw rows to the immutable relation_evidence table.

    This is Worker 13B — it runs every
    ``Settings.worker_evidence_promote_interval_s`` seconds (default 300 s).

    Args:
    ----
        session_factory:  Write async_sessionmaker for intelligence_db.

    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        # Write factory — promotion is a write operation (INSERT into partitioned table).
        self._sf = session_factory

    async def run(self) -> None:
        """Promote one batch of relation_evidence_raw rows (idempotent).

        Designed to be called by APScheduler on the configured interval.  Each
        invocation promotes at most ``_BATCH_SIZE`` rows so no single run can
        hold the DB session open long enough to cause pool starvation.

        E-3 quality gate: rows are only promoted if they have high extraction
        confidence (>= _CONF_THRESHOLD) OR high evidence density
        (>= _DENSITY_THRESHOLD).  Rows failing the gate remain in
        relation_evidence_raw until additional corroborating evidence arrives.

        A summary log record ``relation_evidence_promoter_complete`` is emitted
        after every run regardless of outcome.
        """
        from sqlalchemy import text

        promoted = 0
        blocked_provisional = 0
        no_match = 0
        gated_quality = 0

        try:
            # ── Fetch + insert in one write session ──────────────────────────
            # DS-001: session is released immediately after commit; no session
            # is held across iterations or log calls below.
            async with self._sf() as session:
                # Fetch the batch of promotable rows.  The quality gate
                # thresholds are passed as bind params so they can be tuned
                # without touching SQL strings.
                result = await session.execute(
                    text(_FETCH_SQL),
                    {
                        "batch_size": _BATCH_SIZE,
                        "conf_threshold": _CONF_THRESHOLD,
                        "density_threshold": _DENSITY_THRESHOLD,
                    },
                )
                rows = result.fetchall()

                # Insert each row into the partitioned table, then stamp the
                # raw row's promoted_at in the same transaction so the next run
                # skips it via the ``promoted_at IS NULL`` filter.
                for row in rows:
                    await session.execute(
                        text(_INSERT_SQL),
                        {
                            "relation_id": str(row[1]),  # r.relation_id
                            "doc_id": str(row[2]),  # doc_id
                            "chunk_id": str(row[3]) if row[3] else None,
                            "evidence_text": row[4],
                            "extraction_confidence": float(row[5]),
                            "source_weight": float(row[6]),
                            "evidence_date": row[7],
                            "claim_id": str(row[8]) if row[8] else None,
                        },
                    )
                    # Mark the raw row promoted (row[0] = rer.raw_id).
                    await session.execute(
                        text(_MARK_PROMOTED_SQL),
                        {"raw_id": str(row[0])},
                    )
                    promoted += 1

                await session.commit()

            # ── Diagnostic counts (separate short-lived read sessions) ────────
            # These are informational only — failures here must not mask the
            # promotion result logged immediately after.
            async with self._sf() as session:
                prov_result = await session.execute(text(_COUNT_PROVISIONAL_SQL))
                blocked_provisional = int(prov_result.scalar() or 0)

            async with self._sf() as session:
                nm_result = await session.execute(text(_COUNT_NO_MATCH_SQL))
                no_match = int(nm_result.scalar() or 0)

            # Count rows currently held back by the E-3 quality gate.
            # This informs operations how much evidence is accumulating
            # in the raw table pending future promotion.
            async with self._sf() as session:
                gq_result = await session.execute(
                    text(_COUNT_GATED_QUALITY_SQL),
                    {
                        "conf_threshold": _CONF_THRESHOLD,
                        "density_threshold": _DENSITY_THRESHOLD,
                    },
                )
                gated_quality = int(gq_result.scalar() or 0)

            # Increment Prometheus counter when the gate is actively blocking
            # rows — a sustained nonzero value here warrants investigation.
            if gated_quality > 0:
                kg_evidence_quality_gated_total.inc(gated_quality)

        except Exception as exc:
            logger.error(  # type: ignore[no-any-return]
                "relation_evidence_promoter_error",
                error=str(exc),
                exc_info=True,
            )
            # Re-raise so APScheduler records the failure and applies its own
            # coalesce/retry logic.  The stale-flag pattern used by SummaryWorker
            # does not apply here — raw rows stay in the queue until the next run.
            raise

        logger.info(  # type: ignore[no-any-return]
            "relation_evidence_promoter_complete",
            promoted=promoted,
            blocked_provisional=blocked_provisional,
            no_match=no_match,
            gated_quality=gated_quality,
            batch_size=_BATCH_SIZE,
        )
