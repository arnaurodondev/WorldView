"""Entity mention repository for nlp_db."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select, text, update

from common.time import utc_now  # type: ignore[import-untyped]
from nlp_pipeline.infrastructure.nlp_db.models import EntityMentionModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from nlp_pipeline.domain.models import EntityMention


class EntityMentionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, mention: EntityMention) -> None:
        # Persist resolution_outcome when the in-memory object has one set
        # (e.g. Block 9 sets AUTO_RESOLVED / PROVISIONAL / UNRESOLVED before add)
        resolution_outcome = str(mention.resolution_outcome) if mention.resolution_outcome is not None else "unresolved"
        row = EntityMentionModel(
            mention_id=mention.mention_id,
            doc_id=mention.doc_id,
            section_id=mention.section_id,
            mention_text=mention.mention_text,
            mention_class=str(mention.mention_class),
            confidence=mention.confidence,
            char_start=mention.char_start,
            char_end=mention.char_end,
            resolved_entity_id=mention.resolved_entity_id,
            resolution_confidence=mention.resolution_confidence,
            resolution_stage=mention.resolution_stage,
            ner_model_id=mention.ner_model_id,
            resolution_outcome=resolution_outcome,
            resolution_noise_reason=mention.resolution_noise_reason,
            resolution_processed_at=mention.resolution_processed_at,
        )
        self._session.add(row)

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
                  AND created_at >= now() - interval ':days days'
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
                  AND resolution_processed_at < now() - interval ':minutes minutes'
                RETURNING mention_id
                """,
            ),
            {"minutes": stale_minutes},
        )
        return len(result.fetchall())
