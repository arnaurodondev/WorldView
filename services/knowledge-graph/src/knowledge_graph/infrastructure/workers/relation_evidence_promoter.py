"""Worker 13B: periodic relation_evidence_raw → relation_evidence promotion (PRD §6.7 Block 13B).

Runs every 300 seconds (5 minutes).  Promotes unprocessed rows from the
``relation_evidence_raw`` staging table to the immutable, range-partitioned
``relation_evidence`` table in batches of 200.

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
#   1. entity_provisional = false  → only confirmed entities.
#   2. JOIN relations on the triple (subject, object, canonical_type) to
#      resolve the UUID relation_id — raw rows store the triple, not the UUID.
#   3. NOT EXISTS dedup check against relation_evidence so re-runs are safe.
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
  AND NOT EXISTS (
    SELECT 1 FROM relation_evidence re
    WHERE re.relation_id   = r.relation_id
      AND re.doc_id        = rer.source_document_id
      AND re.evidence_date = rer.evidence_date
  )
  AND rer.extraction_confidence >= :conf_threshold
  -- E-3 density gate (OR branch) is DISABLED (2026-05-20 runtime QA).
  -- The original query referenced `entity_mentions` as a TABLE in
  -- intelligence_db, but that table does not exist — entity mentions
  -- live as a JSONB column `chunks.entity_mentions` in nlp_db, which
  -- R7 forbids us from cross-DB-joining against. Result: the OR branch
  -- threw `relation entity_mentions does not exist` every 5-minute tick
  -- since commit a6452094 (2026-05-10), and because PostgreSQL evaluated
  -- both branches before short-circuiting, the entire promotion pipeline
  -- was broken for 10 days (zero promotions). Restoring the high-
  -- confidence path here keeps the worker functional. Re-enabling the
  -- density gate requires either replicating a mention count into
  -- intelligence_db (preferred — add `mention_count` to canonical_entities
  -- and have nlp-pipeline maintain it via Kafka event) or removing the
  -- density gate from the design altogether. Tracked as a follow-up.
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
  -- Density gate disabled — see _FETCH_SQL for the explanation.
  -- This counter now only counts rows blocked by the confidence gate
  -- (the density signal is unavailable). The :density_threshold parameter
  -- is still accepted at the call site for compatibility but is ignored
  -- by this query — the WHERE clause's density predicate has been removed.
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

                # Insert each row into the partitioned table.
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
