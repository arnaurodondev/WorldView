"""Contradiction repository (PRD §6.7 Block 12b).

Uses raw SQL via ``text()`` — S7 does not own intelligence_db DDL.

Contradiction detection is subject-based (NOT claimer-based):
- Query claims on (subject_entity_id, claim_type, polarity) within a 90-day window.
- A contradiction requires opposite polarity AND both non-neutral.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

from knowledge_graph.application.ports.repositories import ContradictionRepositoryPort

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# 90-day window for contradiction detection
_CONTRADICTION_WINDOW_DAYS: int = 90


class ContradictionRepository(ContradictionRepositoryPort):
    """Read/write repository for ``relation_contradiction_links``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_opposing_claims(
        self,
        subject_entity_id: UUID,
        claim_type: str,
        polarity: str,
        window_days: int = _CONTRADICTION_WINDOW_DAYS,
    ) -> list[dict[str, object]]:
        """Find claims with opposite polarity on the same subject/type within window.

        Returns claims that:
        - Share the same subject_entity_id and claim_type
        - Have opposite, non-neutral polarity to *polarity*
        - Were created within the last *window_days* days
        """
        # Determine the opposite polarity
        opposite = _opposite_polarity(polarity)
        if opposite is None:
            # neutral cannot form a contradiction
            return []

        result = await self._session.execute(
            text("""
SELECT claim_id, claimer_entity_id, polarity, claim_text,
       extraction_confidence, created_at
FROM claims
WHERE subject_entity_id = :subject_entity_id
  AND claim_type        = :claim_type
  AND polarity          = :opposite_polarity
  AND polarity         != 'neutral'
  AND created_at       >= now() - make_interval(days => :window_days)
ORDER BY created_at DESC
"""),
            {
                "subject_entity_id": str(subject_entity_id),
                "claim_type": claim_type,
                "opposite_polarity": opposite,
                "window_days": window_days,
            },
        )
        rows = result.fetchall()
        return [
            {
                "claim_id": UUID(str(r[0])),
                "claimer_entity_id": UUID(str(r[1])) if r[1] else None,
                "polarity": r[2],
                "claim_text": r[3],
                "extraction_confidence": float(r[4]),
                "created_at": r[5],
            }
            for r in rows
        ]

    async def insert_link(
        self,
        relation_evidence_id: UUID,
        claim_id: UUID,
        contradiction_type: str,
        strength: float,
        detected_at: datetime,
    ) -> UUID:
        """Insert a contradiction link into ``relation_contradiction_links``.

        Temporal weights are NOT cached — computed on read.

        COLUMN-NAMING DEBT (2026-06-16 data-pipeline-gaps Gap 1): despite its
        name, ``relation_evidence_id`` does NOT hold a
        ``relation_evidence_raw.raw_id``. The caller
        (``contradiction_batch.py`` Worker 13B) passes the *subject claim's*
        ``claims.claim_id`` here. There is no FK constraint enforcing either
        interpretation. All read paths therefore resolve the subject by joining
        ``claims`` (``c.claim_id = rcl.relation_evidence_id``), NOT
        ``relation_evidence_raw``. Do not "fix" the join back to ``raw_id``
        without first changing the write to store a real ``raw_id`` and adding
        the FK (see report follow-up: rename migration recommended).
        """
        result = await self._session.execute(
            text("""
INSERT INTO relation_contradiction_links (
    relation_evidence_id, claim_id, contradiction_type, strength, detected_at
) VALUES (
    :relation_evidence_id, :claim_id, :contradiction_type, :strength, :detected_at
)
ON CONFLICT (relation_evidence_id, claim_id) DO NOTHING
RETURNING link_id
"""),
            {
                "relation_evidence_id": str(relation_evidence_id),
                "claim_id": str(claim_id),
                "contradiction_type": contradiction_type,
                "strength": strength,
                "detected_at": detected_at,
            },
        )
        row = result.fetchone()
        if row is None:
            # ON CONFLICT DO NOTHING — link already existed, fetch existing
            existing = await self._session.execute(
                text("""
SELECT link_id FROM relation_contradiction_links
WHERE relation_evidence_id = :rel_ev_id AND claim_id = :claim_id
"""),
                {
                    "rel_ev_id": str(relation_evidence_id),
                    "claim_id": str(claim_id),
                },
            )
            existing_row = existing.fetchone()
            return UUID(str(existing_row[0]))  # type: ignore[index]
        return UUID(str(row[0]))

    async def fetch_active_for_subject(
        self,
        subject_entity_id: UUID,
        window_days: int = _CONTRADICTION_WINDOW_DAYS,
    ) -> list[dict[str, object]]:
        """Fetch active contradiction links for the top-K calculation (confidence formula).

        COLUMN-NAMING DEBT (2026-06-16 data-pipeline-gaps Gap 1):
        ``relation_contradiction_links.relation_evidence_id`` is named like a
        ``relation_evidence_raw.raw_id`` FK but actually holds the subject
        ``claims.claim_id`` written by ``insert_link`` from
        ``contradiction_batch.py:99`` (no FK constraint → silently accepted;
        7180/7180 links match ``claims.claim_id``, 0/7180 match
        ``relation_evidence_raw.raw_id``). The previous join via
        ``rer.raw_id = rcl.relation_evidence_id`` returned NOTHING for every
        subject. We resolve the subject through ``claims`` on the stored value.
        """
        result = await self._session.execute(
            text("""
SELECT rcl.link_id, rcl.strength, rcl.detected_at
FROM relation_contradiction_links rcl
JOIN claims c ON c.claim_id = rcl.relation_evidence_id
WHERE c.subject_entity_id = :subject_entity_id
  AND rcl.invalidated_at IS NULL
  AND rcl.detected_at    >= now() - make_interval(days => :window_days)
ORDER BY rcl.detected_at DESC
"""),
            {"subject_entity_id": str(subject_entity_id), "window_days": window_days},
        )
        rows = result.fetchall()
        return [
            {
                "link_id": UUID(str(r[0])),
                "strength": float(r[1]),
                "detected_at": r[2],
            }
            for r in rows
        ]

    async def fetch_claims_for_batch_scan(
        self,
        limit: int = 500,
        window_days: int = _CONTRADICTION_WINDOW_DAYS,
    ) -> list[dict[str, object]]:
        """Fetch unexamined non-neutral claims for the batch contradiction scan (Worker 13B).

        Returns claims ordered by created_at DESC so newest are examined first.
        Uses ``idx_claims_contradiction_detection`` index via WHERE predicate.

        Also JOINs ``relation_evidence_raw`` to resolve the ``raw_id`` needed for
        ``relation_contradiction_links.relation_evidence_id`` (FK → raw_id, NOT claim_id).
        ``relation_evidence_raw_id`` will be ``None`` when no corresponding
        ``relation_evidence_raw`` row exists for the claim.
        """
        result = await self._session.execute(
            text("""
SELECT DISTINCT ON (c.subject_entity_id, c.claim_type)
    c.claim_id, c.subject_entity_id, c.claim_type, c.polarity, c.extraction_confidence,
    rer.raw_id AS relation_evidence_raw_id
FROM claims c
LEFT JOIN relation_evidence_raw rer ON rer.claim_id = c.claim_id
WHERE c.subject_entity_id IS NOT NULL
  AND c.polarity != 'neutral'
  AND c.created_at >= now() - make_interval(days => :window_days)
ORDER BY c.subject_entity_id, c.claim_type, c.created_at DESC
LIMIT :limit
"""),
            {"window_days": window_days, "limit": limit},
        )
        rows = result.fetchall()
        return [
            {
                "claim_id": UUID(str(r[0])),
                "subject_entity_id": UUID(str(r[1])),
                "claim_type": r[2],
                "polarity": r[3],
                "extraction_confidence": float(r[4]),
                # raw_id from relation_evidence_raw — None when no matching row exists.
                # The worker MUST use this as relation_evidence_id (not claim_id).
                "relation_evidence_raw_id": UUID(str(r[5])) if r[5] is not None else None,
            }
            for r in rows
        ]

    async def aggregate_contra_stats_for_active_links(
        self,
        window_days: int = _CONTRADICTION_WINDOW_DAYS,
    ) -> list[dict[str, object]]:
        """Aggregate contradiction stats per relation for active links (T-B-02).

        Resolves each active contradiction link to the relation(s) it scores via
        ``relation_contradiction_links`` → ``claims`` → ``relations`` on the
        **subject entity**.  Aggregates per relation:
          - MAX(strength) AS strongest_contra_score
          - jsonb_object_agg(contradiction_type, count) AS contra_count_by_type
          - MAX(detected_at) AS latest_contra_at

        Returns one row per relation whose subject entity has at least one active
        contradiction link within the detection window.  Also returns the
        relation's current ``confidence`` column so the caller can check the
        invalidation threshold.

        COLUMN-NAMING TRAP (BP-706, 2026-06-22 backend-e2e-coverage-gaps BUG-2):
        ``relation_contradiction_links.relation_evidence_id`` is named like a
        ``relation_evidence_raw.raw_id`` FK, but the detection worker
        (``contradiction_batch.py`` insert_link) stores the SUBJECT claim's
        ``claims.claim_id`` there — there is **no FK constraint**, so a join on
        ``rer.raw_id = rcl.relation_evidence_id`` is silently accepted yet
        matches NOTHING (live proof: 9717/9717 links match ``claims.claim_id``,
        0/9717 match ``relation_evidence_raw.raw_id``). That misjoin was the
        third, missed read path that left this aggregation returning 0 rows on
        every run, so ``relations`` never received any contra columns.

        Why a SUBJECT-only join (not the relation TRIPLE): contradiction
        detection is subject-based — the linked claims are entity-level
        financial/sentiment claims (``OTHER``/``REVENUE_GROWTH``/``MARGIN_CHANGE``…)
        whose ``claim_type`` values are NOT canonical relation types and which
        have NO ``relation_evidence_raw`` rows at all (live: 0/9751 linked claims
        have a matching ``rer.claim_id``). There is therefore no object endpoint
        or canonical_type to resolve a single relation triple. The contradiction
        applies to the entity, so we propagate it to every relation where that
        entity is the subject — matching the two corrected read paths
        (``fetch_active_for_subject`` and ``intelligence_rollup``), which are
        likewise purely subject-keyed.
        """
        result = await self._session.execute(
            text("""
SELECT
    r.relation_id,
    MAX(rcl.strength)                                           AS strongest_contra_score,
    jsonb_object_agg(rcl.contradiction_type, type_counts.cnt)  AS contra_count_by_type,
    MAX(rcl.detected_at)                                        AS latest_contra_at,
    r.confidence                                                AS current_confidence
FROM relation_contradiction_links rcl
JOIN claims c ON c.claim_id = rcl.relation_evidence_id
JOIN relations r ON r.subject_entity_id = c.subject_entity_id
JOIN (
    SELECT
        r2.relation_id,
        rcl2.contradiction_type,
        COUNT(*) AS cnt
    FROM relation_contradiction_links rcl2
    JOIN claims c2 ON c2.claim_id = rcl2.relation_evidence_id
    JOIN relations r2 ON r2.subject_entity_id = c2.subject_entity_id
    WHERE rcl2.invalidated_at IS NULL
      AND rcl2.detected_at >= now() - make_interval(days => :window_days)
    GROUP BY r2.relation_id, rcl2.contradiction_type
) type_counts ON type_counts.relation_id = r.relation_id
              AND type_counts.contradiction_type = rcl.contradiction_type
WHERE rcl.invalidated_at IS NULL
  AND rcl.detected_at >= now() - make_interval(days => :window_days)
GROUP BY r.relation_id, r.confidence
"""),
            {"window_days": window_days},
        )
        rows = result.fetchall()
        return [
            {
                "relation_id": UUID(str(r[0])),
                "strongest_contra_score": float(r[1]),
                "contra_count_by_type": dict(r[2]) if r[2] else {},
                "latest_contra_at": r[3],
                "current_confidence": float(r[4]) if r[4] is not None else None,
            }
            for r in rows
        ]

    async def link_exists(
        self,
        relation_evidence_id: UUID,
        claim_id: UUID,
    ) -> bool:
        """Check whether a contradiction link already exists (skip re-detection)."""
        result = await self._session.execute(
            text("""
SELECT 1 FROM relation_contradiction_links
WHERE relation_evidence_id = :ev_id AND claim_id = :claim_id
LIMIT 1
"""),
            {"ev_id": str(relation_evidence_id), "claim_id": str(claim_id)},
        )
        return result.fetchone() is not None


def _opposite_polarity(polarity: str) -> str | None:
    """Return the opposite non-neutral polarity, or None for neutral."""
    _map = {"positive": "negative", "negative": "positive"}
    return _map.get(polarity)
