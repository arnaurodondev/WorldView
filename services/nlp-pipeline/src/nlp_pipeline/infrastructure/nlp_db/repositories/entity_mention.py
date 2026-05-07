"""Entity mention repository for nlp_db."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from common.time import utc_now  # type: ignore[import-untyped]
from nlp_pipeline.infrastructure.nlp_db.models import EntityMentionModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from nlp_pipeline.domain.models import EntityMention


@dataclass(frozen=True)
class UnresolvedMentionWithContext:
    """Bundle of an unresolved EntityMention plus its surrounding context.

    PLAN-0057 T-B-3-01: the LLM-based unresolved-resolution worker (F-CRIT-05)
    needs domain context to distinguish "iShares Core S&P 500 ETF" (real
    investable fund) from "Q3" (calendar fragment).  The chunk text itself is
    stored in MinIO/S3 (keyed by ``chunks.chunk_text_key``), so we cannot
    extract the literal ±200 chars around the mention purely in SQL.  Instead
    we surface the strongest DB-resident context — the document title and the
    enclosing section title — which together give the LLM enough domain signal
    (e.g. "Singapore central bank press release" → "MAS = Monetary Authority
    of Singapore").  Both fields are nullable because not every doc has them.
    """

    mention: EntityMentionModel
    context_sentence: str | None


class EntityMentionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, mention: EntityMention) -> None:
        """Insert an entity mention row.

        PLAN-0084 B-3 (T-B-3-02): uses ``ON CONFLICT (mention_id) DO NOTHING``
        so that Kafka replays that produce the same deterministic ``mention_id``
        (via ``uuid5_from_parts``) are silently idempotent at the DB level.
        """
        # Persist resolution_outcome when the in-memory object has one set
        # (e.g. Block 9 sets AUTO_RESOLVED / PROVISIONAL / UNRESOLVED before add)
        resolution_outcome = str(mention.resolution_outcome) if mention.resolution_outcome is not None else "unresolved"
        stmt = (
            pg_insert(EntityMentionModel)
            .values(
                mention_id=mention.mention_id,
                doc_id=mention.doc_id,
                section_id=mention.section_id,
                mention_text=mention.mention_text,
                mention_class=str(mention.mention_class),
                confidence=mention.confidence,
                char_start=mention.char_start,
                char_end=mention.char_end,
                resolved_entity_id=mention.resolved_entity_id,
                tenant_id=mention.tenant_id,
                resolution_confidence=mention.resolution_confidence,
                resolution_stage=mention.resolution_stage,
                ner_model_id=mention.ner_model_id,
                resolution_outcome=resolution_outcome,
                resolution_noise_reason=mention.resolution_noise_reason,
                resolution_processed_at=mention.resolution_processed_at,
            )
            .on_conflict_do_nothing(index_elements=["mention_id"])
        )
        await self._session.execute(stmt)

    async def add_batch(self, mentions: list[EntityMention]) -> None:
        for mention in mentions:
            await self.add(mention)

    async def get_by_doc(self, doc_id: UUID) -> list[EntityMentionModel]:
        result = await self._session.execute(select(EntityMentionModel).where(EntityMentionModel.doc_id == doc_id))
        return list(result.scalars().all())

    async def resolve(
        self,
        mention_id: UUID,
        entity_id: UUID,
        confidence: float,
        stage: int,
    ) -> None:
        """Update a mention with resolution result.

        Also sets resolution_outcome='auto_resolved' (R-005 / PLAN-0033 T-C-1-02)
        so the new outcome column tracks Block 9 successes correctly.
        """
        await self._session.execute(
            update(EntityMentionModel)
            .where(EntityMentionModel.mention_id == mention_id)
            .values(
                resolved_entity_id=entity_id,
                resolution_confidence=confidence,
                resolution_stage=stage,
                resolution_outcome="auto_resolved",  # track Block 9 success
            ),
        )

    async def get_unresolved_batch(
        self,
        batch_size: int,
        lookback_days: int = 90,
        *,
        lock: bool = True,
    ) -> list[EntityMentionModel]:
        """Fetch unresolved mentions for re-resolution, with optional row-level lock.

        Uses ``FOR UPDATE SKIP LOCKED`` so concurrent worker instances never
        process the same mention (BP-001 / R22 process isolation).

        Args:
        ----
            batch_size:    Maximum rows to fetch.
            lookback_days: Only consider mentions created within this many days.
            lock:          Whether to acquire FOR UPDATE SKIP LOCKED (default True).
                           Set False in read-only tests.

        """
        lock_clause = "FOR UPDATE SKIP LOCKED" if lock else ""
        result = await self._session.execute(
            text(
                f"""
                SELECT *
                FROM entity_mentions
                WHERE resolution_outcome = 'unresolved'
                  AND created_at >= now() - make_interval(days => :days)
                ORDER BY created_at ASC
                LIMIT :limit
                {lock_clause}
                """,
            ),
            {"days": lookback_days, "limit": batch_size},
        )
        rows = result.fetchall()
        # Re-load as ORM objects for attribute access (needed by worker)
        if not rows:
            return []
        mention_ids = [r[0] for r in rows]  # mention_id is first column
        orm_result = await self._session.execute(
            select(EntityMentionModel).where(
                EntityMentionModel.mention_id.in_(mention_ids),  # type: ignore[attr-defined]
            ),
        )
        return list(orm_result.scalars().all())

    async def get_unresolved_batch_with_context(
        self,
        batch_size: int,
        lookback_days: int = 90,
        *,
        lock: bool = True,
    ) -> list[UnresolvedMentionWithContext]:
        """Fetch unresolved mentions with surrounding domain context.

        PLAN-0057 T-B-3-01 / F-CRIT-05.  Identical lock semantics to
        :py:meth:`get_unresolved_batch` (FOR UPDATE SKIP LOCKED so concurrent
        workers cannot double-process), but additionally LEFT JOINs the
        ``document_source_metadata`` and ``sections`` tables to retrieve
        document-title and section-title strings.  Those strings are
        concatenated into a single ``context_sentence`` field that the
        UnresolvedResolutionWorker passes to the LLM prompt to disambiguate
        ambiguous surface forms (e.g. "MAS" → Monetary Authority of Singapore
        when the title mentions Singapore).

        Why title+section instead of literal ±200 chars from chunk text:
        chunk text lives in MinIO/S3 (referenced by ``chunks.chunk_text_key``)
        and is not joinable in SQL.  Title + section heading are the strongest
        DB-resident contextual signals and add zero S3 round-trips per
        mention — important because a single batch can hit hundreds of rows.

        Args:
        ----
            batch_size:    Maximum rows to fetch.
            lookback_days: Only consider mentions created within this many days.
            lock:          Whether to acquire FOR UPDATE SKIP LOCKED (default True).
                           Set False in read-only tests.

        Returns:
        -------
            List of :class:`UnresolvedMentionWithContext`.  Empty list when no
            unresolved rows exist.

        """
        # Step 1: fetch + lock the unresolved mention IDs.  We cannot do the
        # JOIN in this SELECT because PostgreSQL forbids FOR UPDATE on rows
        # produced by an outer join — so we lock entity_mentions only, then
        # hydrate context in a second non-locking query.
        lock_clause = "FOR UPDATE SKIP LOCKED" if lock else ""
        result = await self._session.execute(
            text(
                f"""
                SELECT mention_id
                FROM entity_mentions
                WHERE resolution_outcome = 'unresolved'
                  AND created_at >= now() - make_interval(days => :days)
                ORDER BY created_at ASC
                LIMIT :limit
                {lock_clause}
                """,
            ),
            {"days": lookback_days, "limit": batch_size},
        )
        rows = result.fetchall()
        if not rows:
            return []
        mention_ids = [r[0] for r in rows]

        # Step 2: load ORM EntityMentionModel rows for attribute access.
        orm_result = await self._session.execute(
            select(EntityMentionModel).where(
                EntityMentionModel.mention_id.in_(mention_ids),  # type: ignore[attr-defined]
            ),
        )
        orm_rows: list[EntityMentionModel] = list(orm_result.scalars().all())

        # Step 3: pull document title + section title in one query.  We use a
        # raw SQL query (not the ORM) because ``document_source_metadata`` is
        # not modelled with a relationship() to entity_mentions — adding one
        # would force a migration that is out of scope for this wave.
        ctx_result = await self._session.execute(
            text(
                """
                SELECT em.mention_id,
                       dsm.title         AS doc_title,
                       s.title           AS section_title
                FROM entity_mentions em
                LEFT JOIN document_source_metadata dsm ON dsm.doc_id = em.doc_id
                LEFT JOIN sections s ON s.section_id = em.section_id
                WHERE em.mention_id = ANY(:ids)
                """,
            ),
            {"ids": mention_ids},
        )
        # Build a lookup so we can attach context to each ORM row in O(1).
        ctx_by_id: dict[UUID, str | None] = {}
        for row in ctx_result.fetchall():
            doc_title = row.doc_title or ""
            section_title = row.section_title or ""
            # Compose a single human-readable context string.  Empty fields
            # are dropped to avoid stray pipes ("|").  None when both empty.
            parts = [p for p in (doc_title.strip(), section_title.strip()) if p]
            ctx_by_id[row.mention_id] = " | ".join(parts) if parts else None

        return [
            UnresolvedMentionWithContext(
                mention=orm_row,
                context_sentence=ctx_by_id.get(orm_row.mention_id),
            )
            for orm_row in orm_rows
        ]

    async def update_resolution_outcome(
        self,
        mention_id: UUID,
        outcome: str,
        noise_reason: str | None = None,
    ) -> None:
        """Update the resolution outcome and set processed_at to now().

        Args:
        ----
            mention_id:   The mention to update.
            outcome:      New ResolutionOutcome string value.
            noise_reason: LLM-provided reason (only set when outcome='noise').

        """
        await self._session.execute(
            update(EntityMentionModel)
            .where(EntityMentionModel.mention_id == mention_id)
            .values(
                resolution_outcome=outcome,
                resolution_noise_reason=noise_reason,
                resolution_processed_at=utc_now(),
            ),
        )

    async def mark_batch_escalated(self, mention_ids: list[UUID]) -> None:
        """Atomically mark a batch of mentions as 'escalated' (worker lock).

        Called immediately after get_unresolved_batch() while still within the
        same transaction so the FOR UPDATE lock is held during the UPDATE.
        """
        if not mention_ids:
            return
        await self._session.execute(
            update(EntityMentionModel)
            .where(EntityMentionModel.mention_id.in_(mention_ids))  # type: ignore[attr-defined]
            .values(resolution_outcome="escalated", resolution_processed_at=utc_now()),
        )

    async def recover_stale_escalated(self, stale_minutes: int = 30) -> int:
        """Reset mentions stuck as 'escalated' for longer than stale_minutes.

        Returns the count of rows reset.  Called on worker startup to recover
        from partial crash mid-batch.
        """
        result = await self._session.execute(
            text(
                """
                UPDATE entity_mentions
                SET resolution_outcome = 'unresolved',
                    resolution_processed_at = NULL
                WHERE resolution_outcome = 'escalated'
                  AND resolution_processed_at < now() - make_interval(mins => :minutes)
                RETURNING mention_id
                """,
            ),
            {"minutes": stale_minutes},
        )
        return len(result.fetchall())

    async def get_articles_for_entity(
        self,
        entity_id: UUID,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Return articles that mention *entity_id*, joined with source metadata.

        Uses a CTE to deduplicate doc_ids across multiple mentions of the same
        entity in a document, then joins ``document_source_metadata`` and
        LEFT JOINs ``routing_decisions`` for composite_score used as
        display_relevance_score.  Results are ordered newest-first.

        Args:
        ----
            entity_id: The resolved entity UUID to filter mentions by.
            limit:     Maximum number of articles to return (1-50).

        Returns:
        -------
            A list of dicts with keys: doc_id, title, url, published_at,
            source_name, source_type, display_relevance_score.

        """
        result = await self._session.execute(
            text(
                """
                WITH entity_docs AS (
                    SELECT DISTINCT doc_id
                    FROM entity_mentions
                    WHERE resolved_entity_id = :entity_id
                )
                SELECT dsm.doc_id,
                       dsm.title,
                       dsm.url,
                       dsm.published_at,
                       dsm.source_name,
                       dsm.source_type,
                       rd.composite_score AS display_relevance_score
                FROM entity_docs ed
                JOIN  document_source_metadata dsm ON dsm.doc_id = ed.doc_id
                LEFT JOIN routing_decisions rd      ON rd.doc_id  = ed.doc_id
                ORDER BY dsm.published_at DESC
                LIMIT :limit
                """
            ),
            {"entity_id": str(entity_id), "limit": limit},
        )
        rows = result.fetchall()
        return [
            {
                "doc_id": row.doc_id,
                "title": row.title,
                "url": row.url,
                "published_at": row.published_at,
                "source_name": row.source_name,
                "source_type": row.source_type,
                "display_relevance_score": (
                    float(row.display_relevance_score) if row.display_relevance_score is not None else None
                ),
            }
            for row in rows
        ]
