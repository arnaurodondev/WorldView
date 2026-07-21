"""DocumentSourceMetadata repository for nlp_db."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from nlp_pipeline.application.ports.repositories import DocumentSourceMetadataRepository
from nlp_pipeline.infrastructure.nlp_db.models import DocumentSourceMetadataModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from nlp_pipeline.domain.models import DocumentSourceMetadata


class SQLAlchemyDocumentSourceMetadataRepository(DocumentSourceMetadataRepository):
    """SQLAlchemy implementation of :class:`DocumentSourceMetadataRepository`.

    ``upsert`` uses ``ON CONFLICT (doc_id) DO NOTHING`` for idempotency —
    the S6 consumer may process the same article twice on replay.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, metadata: DocumentSourceMetadata) -> None:
        insert_stmt = pg_insert(DocumentSourceMetadataModel).values(
            doc_id=metadata.doc_id,
            title=metadata.title,
            url=metadata.url,
            published_at=metadata.published_at,
            source_name=metadata.source_name,
            source_type=metadata.source_type,
            word_count=metadata.word_count,
            created_at=metadata.created_at,
        )
        # On conflict: update title, url and source_name only if they were
        # previously NULL, so backfilled values are never overwritten by
        # subsequent NULL events. ISSUE-B: including source_name here lets rows
        # inserted before the derive-from-source_type fix self-heal when the
        # article is re-processed (the derived label is non-NULL for any known
        # source_type), without clobbering an already-populated value.
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=["doc_id"],
            set_={
                "title": sa.case(
                    (DocumentSourceMetadataModel.title.is_(None), insert_stmt.excluded.title),
                    else_=DocumentSourceMetadataModel.title,
                ),
                "url": sa.case(
                    (DocumentSourceMetadataModel.url.is_(None), insert_stmt.excluded.url),
                    else_=DocumentSourceMetadataModel.url,
                ),
                "source_name": sa.case(
                    (DocumentSourceMetadataModel.source_name.is_(None), insert_stmt.excluded.source_name),
                    else_=DocumentSourceMetadataModel.source_name,
                ),
            },
        )
        await self._session.execute(stmt)

    async def batch_get(self, doc_ids: list[UUID]) -> dict[UUID, DocumentSourceMetadata]:
        from nlp_pipeline.domain.models import DocumentSourceMetadata

        if not doc_ids:
            return {}

        result = await self._session.execute(
            sa.select(DocumentSourceMetadataModel).where(DocumentSourceMetadataModel.doc_id.in_(doc_ids))
        )
        rows = result.scalars().all()
        return {
            row.doc_id: DocumentSourceMetadata(
                doc_id=row.doc_id,
                title=row.title,
                url=row.url,
                published_at=row.published_at,
                source_name=row.source_name,
                source_type=row.source_type,
                word_count=row.word_count,
                created_at=row.created_at,
            )
            for row in rows
        }

    async def get_entity_sentiment_timeseries(
        self,
        entity_id: UUID,
        days: int,
        tenant_id: str | None = None,
    ) -> list[dict[str, object]]:
        """Daily sentiment aggregates for *entity_id* over the last *days* calendar days.

        F-301/F-410: when *tenant_id* is provided (normal authenticated calls),
        the JOIN on entity_mentions is restricted to that tenant's rows.  When
        *tenant_id* is None (system-level JWT with no tenant scope), no tenant
        filter is applied — this is the intentional cross-tenant path for
        internal analytics workers.
        """
        from sqlalchemy import text as sa_text

        # Build the tenant filter clause conditionally.  We never interpolate
        # user-supplied values into the SQL string — tenant_filter is one of
        # two hard-coded literals, so this is injection-safe.
        tenant_clause = "AND em.tenant_id = :tenant_id" if tenant_id is not None else ""
        params: dict[str, object] = {"entity_id": entity_id, "days": days}
        if tenant_id is not None:
            params["tenant_id"] = UUID(tenant_id)

        stmt = sa_text(
            f"""
            SELECT
                date_trunc('day', dsm.published_at AT TIME ZONE 'UTC')::date AS day,
                COUNT(DISTINCT dsm.doc_id)::int AS article_count,
                AVG(dsm.llm_relevance_score)::double precision AS avg_relevance,
                SUM(CASE WHEN dsm.sentiment = 'positive' THEN 1 ELSE 0 END)::double precision
                    / NULLIF(COUNT(DISTINCT dsm.doc_id), 0) AS positive_ratio,
                SUM(CASE WHEN dsm.sentiment = 'negative' THEN 1 ELSE 0 END)::double precision
                    / NULLIF(COUNT(DISTINCT dsm.doc_id), 0) AS negative_ratio,
                AVG(dsm.impact_score)::double precision AS avg_impact_score
            FROM document_source_metadata dsm
            JOIN entity_mentions em
                ON em.doc_id = dsm.doc_id
               AND em.resolved_entity_id = :entity_id
               {tenant_clause}
            WHERE dsm.published_at >= now() - make_interval(days => :days)
              AND dsm.published_at IS NOT NULL
            GROUP BY day
            ORDER BY day ASC
            """
        ).bindparams(**params)

        result = await self._session.execute(stmt)
        rows = result.mappings().all()
        return [
            {
                "date": str(row["day"]),
                "article_count": int(row["article_count"] or 0),
                "avg_relevance": float(row["avg_relevance"]) if row["avg_relevance"] is not None else None,
                "positive_ratio": float(row["positive_ratio"]) if row["positive_ratio"] is not None else None,
                "negative_ratio": float(row["negative_ratio"]) if row["negative_ratio"] is not None else None,
                "avg_impact_score": float(row["avg_impact_score"]) if row["avg_impact_score"] is not None else None,
            }
            for row in rows
        ]
