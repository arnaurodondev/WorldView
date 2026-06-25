"""GetIntelligenceRollup7dUseCase — Wave L-5a (PLAN-0089).

Returns a small rollup that the S3-side screener sync worker materialises
into ``instrument_intelligence_snapshot.recent_contradiction_count`` (Wave L-5b).

R9: this use case reads only from ``intelligence_db`` (S7's own DB), never
from nlp_db. The instrument_id is reused as ``subject_entity_id`` because
``canonical_entities.entity_id`` is set equal to the upstream instrument
UUID for all instrument-type entities (see
``canonical_entity.py:create_or_get`` doc on PLAN-0057 F-DS-03).

R25: read-only use case → caller wires it with a ``ReadOnlyDbSessionDep``.
R27: ditto.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# 7-day window — keep as a module constant so tests can monkey-patch if needed.
_WINDOW_DAYS = 7


@dataclass(frozen=True)
class IntelligenceRollup7d:
    """Small JSON-friendly DTO returned by the use case."""

    recent_contradiction_count: int


class GetIntelligenceRollup7dUseCase:
    """Count active contradictions involving a canonical entity in the last 7 days.

    "Active" = ``invalidated_at IS NULL`` (matches the idx_contra_links_active
    partial index in migration 0001 Block J → query is cheap even for a
    universe-wide nightly sync).
    """

    async def execute(
        self,
        session: AsyncSession,
        instrument_id: UUID,
    ) -> IntelligenceRollup7d:
        """Return the contradiction count for ``instrument_id`` (= entity_id)."""
        # COLUMN-NAMING DEBT (BP / 2026-06-16 data-pipeline-gaps Gap 1):
        # ``relation_contradiction_links.relation_evidence_id`` is named as though
        # it were a ``relation_evidence_raw.raw_id`` FK, but the detection worker
        # (contradiction_batch.py:99) actually writes the *subject claim's*
        # ``claims.claim_id`` into it. There is no FK constraint, so the mismatch
        # was accepted silently. Live proof: 7180/7180 links match
        # ``claims.claim_id`` and 0/7180 match ``relation_evidence_raw.raw_id``.
        #
        # The previous query joined ``rer.raw_id = rcl.relation_evidence_id`` and
        # therefore returned 0 for EVERY instrument (universe-wide zero — the
        # keystone bug that made the "Live Catalysts" screener empty). We resolve
        # the subject by joining ``claims`` on the value actually stored, mirroring
        # the write path.
        sql = text(
            """
            SELECT COUNT(*)
            FROM relation_contradiction_links rcl
            JOIN claims c
                ON c.claim_id = rcl.relation_evidence_id
            WHERE c.subject_entity_id = :entity_id
              AND rcl.invalidated_at IS NULL
              AND rcl.detected_at >= now() - INTERVAL ':days days'::interval
            """.replace(":days", str(_WINDOW_DAYS)),
        )
        # NOTE: ``:days`` is interpolated as a literal because Postgres does
        # not accept a bound parameter inside an INTERVAL literal. The value
        # is a hard-coded module constant (not user input) so there is no
        # injection risk (R9 / Bandit-safe).
        result = await session.execute(sql, {"entity_id": str(instrument_id)})
        row = result.fetchone()
        count = int(row[0]) if row is not None and row[0] is not None else 0
        return IntelligenceRollup7d(recent_contradiction_count=count)
