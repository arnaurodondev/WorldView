"""Concrete implementation of SignalsQueryPort backed by SQLAlchemy ORM models."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import Integer, cast, func, select, text

from nlp_pipeline.application.ports.repositories import SignalsQueryPort
from nlp_pipeline.infrastructure.nlp_db.models import EntityMentionModel, OutboxEventModel, RoutingDecisionModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class SqlaSignalsQueryRepo(SignalsQueryPort):
    """SQLAlchemy-backed implementation of SignalsQueryPort."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_signal_events(
        self,
        limit: int,
        offset: int,
        doc_id: UUID | None,
    ) -> tuple[list[dict[str, Any]], int]:
        q = (
            select(OutboxEventModel)
            .where(OutboxEventModel.topic == "nlp.signal.detected.v1")
            .order_by(OutboxEventModel.created_at.desc())
        )
        if doc_id is not None:
            q = q.where(OutboxEventModel.partition_key == str(doc_id))

        count_q = select(func.count()).select_from(q.subquery())
        total = (await self._session.execute(count_q)).scalar_one()

        result = await self._session.execute(q.limit(limit).offset(offset))
        rows = result.scalars().all()

        return [
            {
                "event_id": row.event_id,
                "partition_key": row.partition_key,
                "payload_avro": row.payload_avro,
                "created_at": row.created_at,
            }
            for row in rows
        ], int(total)

    async def search_entity_mentions(
        self,
        q: str,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
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
        total = (await self._session.execute(count_q)).scalar_one()

        result = await self._session.execute(base_q.limit(limit).offset(offset))
        rows = result.all()

        return [
            {
                "resolved_entity_id": row.resolved_entity_id,
                "mention_text": row.mention_text,
                "mention_class": row.mention_class,
                "mention_count": row.mention_count,
            }
            for row in rows
        ], int(total)

    async def get_entity_detail(self, entity_id: UUID) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(
                EntityMentionModel.mention_class,
                EntityMentionModel.mention_text,
                func.count(EntityMentionModel.mention_id).label("total"),
                func.sum(
                    cast(EntityMentionModel.resolved_entity_id.is_not(None), Integer),
                ).label("resolved"),
            )
            .where(EntityMentionModel.resolved_entity_id == entity_id)
            .group_by(EntityMentionModel.mention_class, EntityMentionModel.mention_text)
            .limit(1),
        )
        row = result.one_or_none()
        if row is None:
            return None

        return {
            "mention_class": row.mention_class,
            "mention_text": row.mention_text,
            "total": row.total,
            "resolved": row.resolved,
        }

    async def get_entity_articles(
        self,
        entity_id: UUID,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        result = await self._session.execute(
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
            .limit(limit),
        )
        rows = result.all()

        total_result = await self._session.execute(
            select(func.count(func.distinct(EntityMentionModel.doc_id))).where(
                EntityMentionModel.resolved_entity_id == entity_id,
            ),
        )
        total = total_result.scalar_one()

        return [
            {
                "doc_id": row.doc_id,
                "routing_tier": row.routing_tier,
                "mention_count": row.mention_count,
            }
            for row in rows
        ], int(total)

    async def vector_search_sections(self, limit: int) -> list[dict[str, Any]]:
        stmt = text(
            """
            SELECT s.section_id, s.doc_id,
                   left(regexp_replace(s.doc_id::text, '-', ''), 40) AS snippet,
                   1.0 AS score
            FROM sections s
            WHERE s.doc_id IS NOT NULL
            LIMIT :limit
            """,
        ).bindparams(limit=limit)
        result = await self._session.execute(stmt)
        rows = result.all()

        return [
            {
                "doc_id": row.doc_id,
                "section_id": row.section_id,
                "score": float(row.score),
                "snippet": str(row.snippet),
            }
            for row in rows
        ]

    async def find_routing_decision(self, doc_id: UUID) -> bool:
        result = await self._session.execute(
            select(RoutingDecisionModel).where(RoutingDecisionModel.doc_id == doc_id).limit(1),
        )
        return result.scalar_one_or_none() is not None

    async def insert_outbox_event(
        self,
        event_id: UUID,
        topic: str,
        partition_key: str,
        payload_avro: bytes,
    ) -> None:
        self._session.add(
            OutboxEventModel(
                event_id=event_id,
                topic=topic,
                partition_key=partition_key,
                payload_avro=payload_avro,
                status="pending",
            ),
        )
        await self._session.commit()
