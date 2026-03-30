"""Query use cases for the NLP Pipeline REST API (S6).

All infrastructure imports are encapsulated here so that api/routes/signals.py
imports only from the application layer (R25 / IG-LAYER-002 compliance).
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from nlp_pipeline.infrastructure.nlp_db.models import (
    EntityMentionModel,
    OutboxEventModel,
    RoutingDecisionModel,
)
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_log = get_logger(__name__)  # type: ignore[no-any-return]


# ── Application-layer result dataclasses ──────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class SignalData:
    signal_id: UUID
    doc_id: UUID
    entity_id: UUID
    signal_type: str
    confidence: float
    evidence_text: str
    detected_at: datetime


@dataclasses.dataclass(frozen=True)
class EntitySearchData:
    entity_id: UUID
    canonical_name: str
    entity_type: str
    mention_count: int


@dataclasses.dataclass(frozen=True)
class EntityDetailData:
    entity_id: UUID
    canonical_name: str
    entity_type: str
    mention_count: int
    resolved_count: int
    provisional_count: int


@dataclasses.dataclass(frozen=True)
class EntityArticleData:
    doc_id: UUID
    routing_tier: str
    mention_count: int


@dataclasses.dataclass(frozen=True)
class VectorSearchHitData:
    doc_id: UUID
    section_id: UUID
    score: float
    snippet: str


# ── Use case classes ───────────────────────────────────────────────────────────


class ListSignalsUseCase:
    """List outbox events for the nlp.signal.detected.v1 topic."""

    async def execute(
        self,
        session: AsyncSession,
        limit: int,
        offset: int,
        doc_id: UUID | None,
    ) -> tuple[list[SignalData], int]:
        from sqlalchemy import func, select

        q = (
            select(OutboxEventModel)
            .where(OutboxEventModel.topic == "nlp.signal.detected.v1")
            .order_by(OutboxEventModel.created_at.desc())
        )
        if doc_id is not None:
            q = q.where(OutboxEventModel.partition_key == str(doc_id))

        count_q = select(func.count()).select_from(q.subquery())
        total = (await session.execute(count_q)).scalar_one()

        result = await session.execute(q.limit(limit).offset(offset))
        rows = result.scalars().all()

        items: list[SignalData] = []
        for row in rows:
            try:
                payload = json.loads(row.payload_avro)
                items.append(
                    SignalData(
                        signal_id=UUID(payload.get("event_id", str(row.event_id))),
                        doc_id=UUID(payload.get("doc_id", row.partition_key)),
                        entity_id=UUID(
                            str(
                                payload.get("claimer_entity_id")
                                or payload.get(
                                    "subject_entity_id",
                                    "00000000-0000-0000-0000-000000000000",
                                )
                            )
                        ),
                        signal_type=str(payload.get("claim_type", "unknown")),
                        confidence=float(payload.get("extraction_confidence", 0.0)),
                        evidence_text=str(payload.get("claim_id", "")),
                        detected_at=datetime.fromisoformat(payload["occurred_at"])
                        if "occurred_at" in payload
                        else row.created_at,
                    )
                )
            except Exception:
                _log.debug("signals.list_skip_malformed_payload", exc_info=True)
                continue

        return items, int(total)


class SearchEntitiesUseCase:
    """Search entities by mention text substring."""

    async def execute(
        self,
        session: AsyncSession,
        q: str,
        limit: int,
        offset: int,
    ) -> tuple[list[EntitySearchData], int]:
        from sqlalchemy import func, select

        base_q = select(
            EntityMentionModel.resolved_entity_id,
            EntityMentionModel.mention_text,
            EntityMentionModel.mention_class,
            func.count(EntityMentionModel.mention_id).label("mention_count"),
        ).where(EntityMentionModel.resolved_entity_id.is_not(None))

        if q:
            base_q = base_q.where(EntityMentionModel.mention_text.ilike(f"%{q}%"))

        base_q = base_q.group_by(
            EntityMentionModel.resolved_entity_id,
            EntityMentionModel.mention_text,
            EntityMentionModel.mention_class,
        )

        count_q = select(func.count()).select_from(base_q.subquery())
        total = (await session.execute(count_q)).scalar_one()

        result = await session.execute(base_q.limit(limit).offset(offset))
        rows = result.all()

        return [
            EntitySearchData(
                entity_id=UUID(str(row.resolved_entity_id)),
                canonical_name=str(row.mention_text),
                entity_type=str(row.mention_class),
                mention_count=int(row.mention_count),
            )
            for row in rows
        ], int(total)


class GetEntityDetailUseCase:
    """Retrieve entity detail with mention resolution counts."""

    async def execute(
        self,
        session: AsyncSession,
        entity_id: UUID,
    ) -> EntityDetailData | None:
        from sqlalchemy import func, select

        result = await session.execute(
            select(
                EntityMentionModel.mention_class,
                EntityMentionModel.mention_text,
                func.count(EntityMentionModel.mention_id).label("total"),
                func.sum(
                    func.cast(EntityMentionModel.resolved_entity_id.is_not(None), func.Integer)  # type: ignore[arg-type]
                ).label("resolved"),
            )
            .where(EntityMentionModel.resolved_entity_id == entity_id)
            .group_by(EntityMentionModel.mention_class, EntityMentionModel.mention_text)
            .limit(1)
        )
        row = result.one_or_none()
        if row is None:
            return None

        total = int(row.total)
        resolved = int(row.resolved or 0)
        return EntityDetailData(
            entity_id=entity_id,
            canonical_name=str(row.mention_text),
            entity_type=str(row.mention_class),
            mention_count=total,
            resolved_count=resolved,
            provisional_count=total - resolved,
        )


class GetEntityArticlesUseCase:
    """List articles that mention a given entity."""

    async def execute(
        self,
        session: AsyncSession,
        entity_id: UUID,
        limit: int,
    ) -> tuple[list[EntityArticleData], int]:
        from sqlalchemy import func, select

        result = await session.execute(
            select(
                EntityMentionModel.doc_id,
                RoutingDecisionModel.routing_tier,
                RoutingDecisionModel.decided_at,
                func.count(EntityMentionModel.mention_id).label("mention_count"),
            )
            .join(RoutingDecisionModel, RoutingDecisionModel.doc_id == EntityMentionModel.doc_id)
            .where(EntityMentionModel.resolved_entity_id == entity_id)
            .group_by(
                EntityMentionModel.doc_id,
                RoutingDecisionModel.routing_tier,
                RoutingDecisionModel.decided_at,
            )
            .order_by(RoutingDecisionModel.decided_at.desc())
            .limit(limit)
        )
        rows = result.all()

        total_result = await session.execute(
            select(func.count(func.distinct(EntityMentionModel.doc_id))).where(
                EntityMentionModel.resolved_entity_id == entity_id
            )
        )
        total = total_result.scalar_one()

        return [
            EntityArticleData(
                doc_id=UUID(str(row.doc_id)),
                routing_tier=str(row.routing_tier),
                mention_count=int(row.mention_count),
            )
            for row in rows
        ], int(total)


class VectorSearchUseCase:
    """Semantic section search (keyword fallback until ML client injected)."""

    async def execute(
        self,
        session: AsyncSession,
        limit: int,
    ) -> list[VectorSearchHitData]:
        from sqlalchemy import text

        stmt = text(
            """
            SELECT s.section_id, s.doc_id,
                   left(regexp_replace(s.doc_id::text, '-', ''), 40) AS snippet,
                   1.0 AS score
            FROM sections s
            WHERE s.doc_id IS NOT NULL
            LIMIT :limit
            """
        ).bindparams(limit=limit)
        result = await session.execute(stmt)
        rows = result.all()

        return [
            VectorSearchHitData(
                doc_id=row.doc_id,
                section_id=row.section_id,
                score=float(row.score),
                snippet=str(row.snippet),
            )
            for row in rows
        ]


class ReprocessArticleUseCase:
    """Enqueue a reprocess event for an article.

    Returns True when the article was found and the event was queued,
    False when no routing decision exists for the article.
    """

    async def execute(
        self,
        session: AsyncSession,
        article_id: UUID,
    ) -> bool:
        from sqlalchemy import select

        result = await session.execute(
            select(RoutingDecisionModel).where(RoutingDecisionModel.doc_id == article_id).limit(1)
        )
        if result.scalar_one_or_none() is None:
            return False

        payload = json.dumps(
            {
                "event_id": str(new_uuid7()),
                "event_type": "nlp.reprocess.requested",
                "occurred_at": utc_now().isoformat(),
                "doc_id": str(article_id),
            }
        ).encode()
        session.add(
            OutboxEventModel(
                event_id=new_uuid7(),
                topic="nlp.reprocess.v1",
                partition_key=str(article_id),
                payload_avro=payload,
                status="pending",
            )
        )
        await session.commit()
        return True
