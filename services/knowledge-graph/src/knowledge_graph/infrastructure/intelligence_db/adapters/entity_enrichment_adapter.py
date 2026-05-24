"""EntityEnrichmentAdapter — EntityEnrichmentPort implementation for intelligence_db.

Implements:
  - write_enrichment_result: JSONB merge + column update on canonical_entities
  - increment_attempts:      +1 on enrichment_attempts (SQL-side increment)
  - list_unenriched:         phase-1 batch query; opens/closes its own session
  - seed_relations:          upserts structured-enrichment relations from registry mappings

R25 compliance: methods that receive a ``session`` parameter use the caller's session so
the use case controls the transaction boundary.  ``list_unenriched`` opens its own session
and MUST NOT be called while a DB session is held open by the caller (3-phase pattern).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import text

from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.domain.enrichment_result import EnrichmentResult
    from knowledge_graph.domain.models import CanonicalEntity

# Maps relation canonical_type to the expected entity_type of the object entity.
# Must match the LOWERCASE canonical_type values seeded by:
#   - migration 0001 (listed_on, headquartered_in)
#   - migration 0002 (is_in_sector, is_in_industry)
# Migration 0023 attaches data_source='market_data' + source_field metadata to
# these four rows so this adapter can drive structured-enrichment relation upserts.
_CANONICAL_TYPE_OBJECT_ENTITY_TYPES: dict[str, str] = {
    "is_in_sector": "sector",
    "is_in_industry": "industry",
    "headquartered_in": "country",
    "listed_on": "exchange",
}

# Defense-in-depth allow-list (QA F-S05). Any future registry row whose
# source_field is outside this set is skipped, preventing accidental upserts
# driven by attacker-controlled metadata keys or careless future seeds.
_ALLOWED_SOURCE_FIELDS: frozenset[str] = frozenset(
    {"sector", "industry", "country", "exchange", "ticker", "currency_code"},
)


class EntityEnrichmentAdapter:
    """Port implementation for enrichment result persistence (PRD-0073 §9.4)."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        read_session_factory: Any = None,
    ) -> None:
        self._sf = session_factory
        # DEF-034 (Wave B-5): ``list_unenriched`` is a pure SELECT and routes
        # through the read replica when configured.  The mutation methods
        # (``write_enrichment_result``, ``increment_attempts``, ``seed_relations``)
        # all take a caller-supplied session and stay on the write path.
        self._read_session_factory: Any = read_session_factory if read_session_factory is not None else session_factory

    # ------------------------------------------------------------------
    # EntityEnrichmentPort methods
    # ------------------------------------------------------------------

    async def write_enrichment_result(
        self,
        result: EnrichmentResult,
        session: AsyncSession,
    ) -> None:
        """Merge enrichment result into canonical_entities; caller commits.

        Uses ``jsonb_strip_nulls(metadata || :new_meta::jsonb)`` to preserve
        existing keys not in the new result.

        QA F-X13: Only reset ``enrichment_attempts=0`` when the result actually
        carries a description. An "empty" enrichment (no description) means the
        external source had nothing useful — preserving the prior attempt count
        keeps the entity on the back-off / dead-letter path rather than letting
        a worthless write forgive prior failures.

        QA F-D05: Idempotency guard against redelivery. The WHERE clause refuses
        to overwrite a row whose ``enriched_at`` is already newer than the
        incoming result; redelivered Kafka events therefore can't stomp a fresher
        result with stale data.
        """
        await session.execute(
            text("""
UPDATE canonical_entities
SET
    description        = :description,
    metadata           = jsonb_strip_nulls(metadata || :new_meta::jsonb),
    data_completeness  = :data_completeness,
    enriched_at        = :enriched_at,
    enrichment_attempts = CASE
        WHEN :description IS NULL THEN enrichment_attempts
        ELSE 0
    END
WHERE entity_id = :entity_id
  AND (enriched_at IS NULL OR enriched_at < :enriched_at)
"""),
            {
                "entity_id": str(result.entity_id),
                "description": result.description,
                "new_meta": json.dumps({k: v for k, v in result.metadata.items() if v is not None}),
                "data_completeness": result.data_completeness,
                "enriched_at": result.enriched_at.isoformat(),
            },
        )

    async def increment_attempts(
        self,
        entity_id: UUID,
        session: AsyncSession,
    ) -> None:
        """Increment enrichment_attempts by 1 via SQL-side arithmetic; caller commits."""
        await session.execute(
            text("""
UPDATE canonical_entities
SET enrichment_attempts = enrichment_attempts + 1
WHERE entity_id = :entity_id
"""),
            {"entity_id": str(entity_id)},
        )

    async def decrement_attempts(
        self,
        entity_id: UUID,
        session: AsyncSession,
    ) -> None:
        """PLAN-0093 T-C-4-01: undo a claim-time increment for retryable errors.

        ``claim_for_enrichment`` unconditionally bumps ``enrichment_attempts``
        so the counter advances even when the worker crashes mid-enrichment.
        But retryable errors (transient 429s, network blips) shouldn't burn an
        attempt — they're guaranteed-to-be-tried-again-soon failures, not
        evidence that the entity can't be enriched. The worker calls this
        method in the RetryableEnrichmentError branch to roll the claim back.

        Floor-clamped at 0 (defensive — should never go negative under normal
        flow because the corresponding claim incremented from >= 0).
        """
        await session.execute(
            text("""
UPDATE canonical_entities
SET enrichment_attempts = GREATEST(enrichment_attempts - 1, 0)
WHERE entity_id = :entity_id
"""),
            {"entity_id": str(entity_id)},
        )

    async def list_unenriched(self, batch_size: int) -> list[CanonicalEntity]:
        """Return up to batch_size entities eligible for enrichment.

        Opens and closes its own session (Phase 1 of 3-phase R25 pattern).
        Caller must NOT hold a session open when calling this method.

        QA F-D04 / F-P2-01: ORDER BY aligned to the partial index
        ``ix_canonical_entities_enrichment_sweep (enrichment_attempts, enriched_at)``
        WHERE enrichment_attempts < 3. Postgres can only walk an index for
        ORDER BY when the leading sort key matches the leading index column —
        so we sort by ``enrichment_attempts ASC`` first (low-attempt entities
        before exhausted ones), then ``enriched_at ASC NULLS FIRST`` (oldest
        stale rows + never-enriched rows first within an attempt bucket). This
        keeps the sweep both index-friendly and FIFO-ish.

        PLAN-0093 C-4 (F-DB-ENRICHMENT-001 / F-DB-005): this method is read-only
        and does NOT claim the rows — concurrent workers can race on the same
        entity, and a worker that crashes mid-enrichment never advances the
        attempts counter. Prefer the new :py:meth:`claim_for_enrichment` for
        production code; ``list_unenriched`` is kept for tests + diagnostics
        that need to inspect candidates without mutating state.
        """
        from knowledge_graph.domain.models import CanonicalEntity

        # DEF-034 (Wave B-5): pure SELECT — runs on the read replica when
        # configured.  Falls back to the write factory when no replica is
        # wired (default in tests + dev environments).
        async with self._read_session_factory() as session:
            result = await session.execute(
                text("""
SELECT entity_id, canonical_name, entity_type, ticker, isin, exchange,
       metadata, enrichment_attempts, description, data_completeness, enriched_at
FROM canonical_entities
WHERE (enriched_at IS NULL OR data_completeness < 0.5)
  AND enrichment_attempts < 3
ORDER BY enrichment_attempts ASC, enriched_at ASC NULLS FIRST
LIMIT :batch_size
"""),
                {"batch_size": batch_size},
            )
            rows = result.fetchall()

        return [
            CanonicalEntity(
                entity_id=UUID(str(row[0])),
                canonical_name=str(row[1]),
                entity_type=str(row[2]),
                ticker=row[3],
                isin=row[4],
                exchange=row[5],
                metadata=dict(row[6]) if row[6] else {},
                enrichment_attempts=int(row[7]),
                description=row[8],
                data_completeness=float(row[9]) if row[9] is not None else None,
                enriched_at=row[10],
            )
            for row in rows
        ]

    async def claim_for_enrichment(self, batch_size: int) -> list[CanonicalEntity]:
        """PLAN-0093 T-C-4-01 — atomic claim + attempt-increment in one SQL.

        Solves F-DB-ENRICHMENT-001 / F-DB-005 (counter frozen at 0). The old
        flow was:

            1. SELECT eligible rows                 (list_unenriched)
            2. (worker loop calls enrich)
            3. on FAIL only: UPDATE +1              (increment_attempts)

        Two failure modes:
          - Worker crashes between step 1 and step 3 -> attempts never advances
            -> partial-index keeps the row forever.
          - Two workers race on the same row -> both succeed/fail with the same
            stale value -> wasted LLM cycles + accounting drift.

        The fix is one atomic UPDATE ... RETURNING that does both at claim
        time. Rows whose attempts were already maxed out, or which another
        worker has just snatched, are not returned -> the caller skips them.

        The CTE picks eligible rows with the SAME ordering as
        ``list_unenriched`` (matches the partial-index walk), then the outer
        UPDATE locks + bumps + returns the claimed rows in one round-trip.
        ``FOR UPDATE SKIP LOCKED`` inside the CTE prevents two workers from
        ever picking the same row.

        After enrichment SUCCESS the existing ``write_enrichment_result``
        resets ``enrichment_attempts=0`` (CASE WHEN description IS NOT NULL),
        so a successful claim still recovers fully. After enrichment FAILURE
        nothing extra is needed — the +1 happened at claim time.
        """
        from knowledge_graph.domain.models import CanonicalEntity

        async with self._sf() as session:
            result = await session.execute(
                text("""
WITH eligible AS (
    SELECT entity_id
    FROM canonical_entities
    WHERE (enriched_at IS NULL OR data_completeness < 0.5)
      AND enrichment_attempts < 3
    ORDER BY enrichment_attempts ASC, enriched_at ASC NULLS FIRST
    LIMIT :batch_size
    FOR UPDATE SKIP LOCKED
)
UPDATE canonical_entities ce
SET enrichment_attempts = ce.enrichment_attempts + 1
FROM eligible
WHERE ce.entity_id = eligible.entity_id
  AND ce.enrichment_attempts < 3
RETURNING ce.entity_id, ce.canonical_name, ce.entity_type, ce.ticker,
          ce.isin, ce.exchange, ce.metadata, ce.enrichment_attempts,
          ce.description, ce.data_completeness, ce.enriched_at
"""),
                {"batch_size": batch_size},
            )
            rows = result.fetchall()
            await session.commit()

        return [
            CanonicalEntity(
                entity_id=UUID(str(row[0])),
                canonical_name=str(row[1]),
                entity_type=str(row[2]),
                ticker=row[3],
                isin=row[4],
                exchange=row[5],
                metadata=dict(row[6]) if row[6] else {},
                enrichment_attempts=int(row[7]),
                description=row[8],
                data_completeness=float(row[9]) if row[9] is not None else None,
                enriched_at=row[10],
            )
            for row in rows
        ]

    async def seed_relations(
        self,
        entity_id: UUID,
        metadata: dict[str, object],
        session: AsyncSession,
    ) -> list[str]:
        """Upsert structural enrichment relations from relation_type_registry mappings.

        Queries registry rows with ``data_source = 'market_data'`` and a non-null
        ``source_field``. For each row whose source_field value is present in
        ``metadata``, looks up the object canonical entity and upserts a relation
        row with ``relation_source = 'structured_enrichment'``.

        QA F-S05: source_field is checked against an allow-list before being used,
        so a future registry insert with an unexpected field name won't silently
        drive a relation upsert.

        QA F-D06: ON CONFLICT preserves an existing ``relation_source`` (e.g. an
        nlp_extraction provenance) instead of stomping it with
        ``structured_enrichment``. We use COALESCE so that NULL provenance is
        promoted to ``structured_enrichment`` but a real provenance is kept.

        Returns the list of canonical_type values actually seeded.
        """
        # Fetch applicable registry rows (data added by migration 0023)
        reg_result = await session.execute(
            text("""
SELECT canonical_type, source_field
FROM relation_type_registry
WHERE data_source = 'market_data' AND source_field IS NOT NULL
"""),
        )
        registry_rows = reg_result.fetchall()

        seeded: list[str] = []
        for canonical_type, source_field in registry_rows:
            # F-S05 defense-in-depth: skip unknown source_field values even if
            # the registry somehow contains them. This prevents future seed bugs
            # from triggering unexpected DB writes here.
            if source_field not in _ALLOWED_SOURCE_FIELDS:
                continue

            value = metadata.get(source_field)
            if not value:
                continue

            canonical_type_lower = canonical_type.lower()
            obj_entity_type = _CANONICAL_TYPE_OBJECT_ENTITY_TYPES.get(canonical_type_lower)
            if not obj_entity_type:
                continue

            # Look up the object entity by name + type
            obj_result = await session.execute(
                text("""
SELECT entity_id FROM canonical_entities
WHERE canonical_name = :name AND entity_type = :entity_type
LIMIT 1
"""),
                {"name": str(value), "entity_type": obj_entity_type},
            )
            obj_row = obj_result.fetchone()
            if not obj_row:
                continue

            object_entity_id = UUID(str(obj_row[0]))
            relation_id = new_uuid7()

            await session.execute(
                text("""
INSERT INTO relations (
    relation_id, subject_entity_id, object_entity_id, canonical_type,
    semantic_mode, decay_class, decay_alpha, base_confidence,
    confidence_stale, summary_stale,
    evidence_count, first_evidence_at, latest_evidence_at,
    relation_source
)
VALUES (
    :relation_id, :subject, :object, :canonical_type,
    'RELATION_STATE', 'DURABLE', 0.000950, 0.70,
    true, true,
    0, :now, :now,
    'structured_enrichment'
)
ON CONFLICT (subject_entity_id, object_entity_id, canonical_type)
DO UPDATE SET
    relation_source = COALESCE(relations.relation_source, 'structured_enrichment'),
    latest_evidence_at = EXCLUDED.latest_evidence_at
"""),
                {
                    "relation_id": str(relation_id),
                    "subject": str(entity_id),
                    "object": str(object_entity_id),
                    "canonical_type": canonical_type,
                    "now": utc_now().isoformat(),
                },
            )
            seeded.append(canonical_type)

        return seeded
