"""TemporalEventRepository + EntityEventExposureRepository — SQLAlchemy implementations.

These repositories implement the port interfaces defined in the application layer.
Uses raw SQL via ``text()`` — S7 does not own intelligence_db DDL.

Natural-key deduplication for temporal events:
  ``(event_type, region, title, date_trunc('day', timezone('UTC', active_from)))``

GLOBAL-scope events link only to sector/industry canonical entities; per-company
exposure is inferred at query time via ``is_in_sector`` traversal (PRD-0018 §6.2).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

from knowledge_graph.application.ports.temporal_event_repository import (
    EntityEventExposureRepositoryPort,
    TemporalEventRepositoryPort,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class TemporalEventRepository(TemporalEventRepositoryPort):
    """Read/write repository for ``temporal_events`` in intelligence_db."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_by_natural_key(
        self,
        *,
        event_id: UUID,
        event_type: str,
        scope: str,
        region: str | None,
        title: str,
        active_from: datetime,
        confidence: float,
        description: str | None = None,
        source_article_ids: list[str] | None = None,
        source_url: str | None = None,
        active_until: datetime | None = None,
        residual_impact_days: int = 90,
    ) -> UUID:
        """Upsert a temporal event using the natural deduplication key.

        ON CONFLICT fires when ``(event_type, region, title, date_trunc('day', timezone('UTC', active_from)))``
        matches an existing row.  The conflict target requires region to be non-NULL;
        for NULL-region (LOCAL) events the insert always proceeds.

        Note: ``source_article_ids`` is passed as a Python list of UUID strings;
        asyncpg binds Python lists to PostgreSQL array columns automatically.

        Note on NULL ``region`` (BP-131): PostgreSQL treats NULL ≠ NULL in unique
        indexes.  LOCAL events with ``region=None`` and identical
        ``(event_type, title, active_from::date)`` do NOT conflict — two rows
        can coexist.  The Valkey event-id dedup in the Kafka consumer prevents
        re-delivery of the same Kafka message; semantic duplicates from
        independently-triggered NLP enrichment of the same content are
        theoretically possible but rare.  A future ``NULLS NOT DISTINCT`` index
        (PG 15+) would eliminate this gap.
        """
        ids: list[str] = [str(uid) for uid in (source_article_ids or [])]

        result = await self._session.execute(
            text("""
INSERT INTO temporal_events (
    event_id, event_type, scope, region, title, description,
    source_article_ids, source_url, active_from, active_until,
    residual_impact_days, confidence
) VALUES (
    :event_id, :event_type, :scope, :region, :title, :description,
    :source_article_ids, :source_url, :active_from, :active_until,
    :residual_impact_days, :confidence
)
ON CONFLICT (event_type, region, title, date_trunc('day', timezone('UTC', active_from))) DO UPDATE SET
    scope                = EXCLUDED.scope,
    description          = EXCLUDED.description,
    source_url           = EXCLUDED.source_url,
    active_until         = EXCLUDED.active_until,
    residual_impact_days = EXCLUDED.residual_impact_days,
    confidence           = EXCLUDED.confidence,
    updated_at           = now()
RETURNING event_id
"""),
            {
                "event_id": str(event_id),
                "event_type": event_type,
                "scope": scope,
                "region": region,
                "title": title,
                "description": description,
                "source_article_ids": ids,
                "source_url": source_url,
                "active_from": active_from,
                "active_until": active_until,
                "residual_impact_days": residual_impact_days,
                "confidence": confidence,
            },
        )
        from uuid import UUID as _UUID

        row = result.fetchone()
        return _UUID(str(row[0]))  # type: ignore[index]

    async def list_active(
        self,
        *,
        scope: str | None = None,
        entity_id: UUID | None = None,
        active_only: bool = True,
        event_type: str | None = None,
        region: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, object]], int]:
        """List temporal events with flexible filter composition.

        Builds the WHERE clause dynamically using only hardcoded SQL fragment
        strings — all user-supplied values are bound via named parameters to
        prevent SQL injection.

        ``active_only=True`` excludes EXPIRED events:
            EXPIRED when active_until IS NOT NULL AND
                (now() - active_until) > residual_impact_days days.
        ``entity_id`` filter uses an EXISTS subquery on entity_event_exposures.
        ``exposed_entity_count`` is a correlated subquery count per event row.
        ``COUNT(*) OVER()`` returns total matching rows before LIMIT/OFFSET.
        """
        conditions: list[str] = ["1=1"]
        params: dict[str, object] = {"limit": limit, "offset": offset}

        if scope is not None:
            conditions.append("te.scope = :scope")
            params["scope"] = scope

        if event_type is not None:
            conditions.append("te.event_type = :event_type")
            params["event_type"] = event_type

        if region is not None:
            conditions.append("te.region = :region")
            params["region"] = region

        if from_date is not None:
            conditions.append("te.active_from >= :from_date")
            params["from_date"] = from_date

        if to_date is not None:
            conditions.append("te.active_from <= :to_date")
            params["to_date"] = to_date

        if active_only:
            # Exclude EXPIRED: active_until IS NULL (still active) OR within residual window
            conditions.append(
                "(te.active_until IS NULL OR now() - te.active_until <= te.residual_impact_days * INTERVAL '1 day')",
            )

        if entity_id is not None:
            conditions.append(
                "EXISTS ("
                "SELECT 1 FROM entity_event_exposures eee"
                " WHERE eee.event_id = te.event_id"
                "   AND eee.entity_id = :entity_id"
                ")",
            )
            params["entity_id"] = str(entity_id)

        where_clause = "\n  AND ".join(conditions)
        query = f"""
SELECT
    te.event_id,
    te.event_type,
    te.scope,
    te.region,
    te.title,
    te.description,
    te.source_article_ids,
    te.source_url,
    te.active_from,
    te.active_until,
    te.residual_impact_days,
    te.confidence,
    te.created_at,
    (SELECT COUNT(*) FROM entity_event_exposures WHERE event_id = te.event_id)
        AS exposed_entity_count,
    COUNT(*) OVER() AS total_count
FROM temporal_events te
WHERE {where_clause}
ORDER BY te.active_from DESC
LIMIT :limit OFFSET :offset
"""
        result = await self._session.execute(text(query), params)
        rows = result.fetchall()
        if not rows:
            return [], 0

        from uuid import UUID as _UUID

        events: list[dict[str, object]] = [
            {
                "event_id": _UUID(str(row[0])),
                "event_type": row[1],
                "scope": row[2],
                "region": row[3],
                "title": row[4],
                "description": row[5],
                "source_article_ids": list(row[6]) if row[6] else [],
                "source_url": row[7],
                "active_from": row[8],
                "active_until": row[9],
                "residual_impact_days": int(row[10]),
                "confidence": float(row[11]),
                "created_at": row[12],
                "exposed_entity_count": int(row[13]),
            }
            for row in rows
        ]
        total_count = int(rows[0][14])
        return events, total_count


class EntityEventExposureRepository(EntityEventExposureRepositoryPort):
    """Write repository for ``entity_event_exposures`` in intelligence_db.

    Enforces the unique constraint ``(event_id, entity_id, exposure_type)``:
    duplicate inserts are silently ignored via ON CONFLICT DO NOTHING.
    GLOBAL-scope events must only link to sector/industry canonical entities
    (enforced at the consumer/worker layer — not this repository).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        exposure_id: UUID,
        event_id: UUID,
        entity_id: UUID,
        exposure_type: str,
        confidence: float,
        evidence_text: str | None = None,
        polarity: str | None = None,
        polarity_confidence: float | None = None,
    ) -> UUID:
        """Insert an entity-event exposure link — ON CONFLICT DO NOTHING.

        Returns the exposure_id of the newly inserted row, or the provided
        exposure_id if the row already existed (the caller owns the ID).
        The existing row's exposure_id is not returned from the DB on conflict
        to keep the query simple; callers that need the pre-existing ID should
        query separately.

        ``polarity`` / ``polarity_confidence`` (PLAN-0056 Wave C2, migration
        0066) carry a directional signal for prediction-event exposures. Both
        default to None so existing non-directional callers (earnings, macro,
        geopolitical) keep NULL polarity — the ``ck_exposure_polarity`` CHECK
        allows NULL. The Wave C3 classifier supplies 'bullish'/'bearish'/'neutral'.
        """
        await self._session.execute(
            text("""
INSERT INTO entity_event_exposures (
    exposure_id, event_id, entity_id, exposure_type, confidence, evidence_text,
    polarity, polarity_confidence
) VALUES (
    :exposure_id, :event_id, :entity_id, :exposure_type, :confidence, :evidence_text,
    :polarity, :polarity_confidence
)
ON CONFLICT (event_id, entity_id, exposure_type) DO NOTHING
"""),
            {
                "exposure_id": str(exposure_id),
                "event_id": str(event_id),
                "entity_id": str(entity_id),
                "exposure_type": exposure_type,
                "confidence": confidence,
                "evidence_text": evidence_text,
                "polarity": polarity,
                "polarity_confidence": polarity_confidence,
            },
        )
        return exposure_id
