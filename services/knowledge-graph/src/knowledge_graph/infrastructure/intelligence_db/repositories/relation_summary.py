"""RelationSummary repository (PRD §6.7 Block 13C).

Uses raw SQL via ``text()`` — S7 does not own intelligence_db DDL.

Insert pattern: set old summaries ``is_current=false`` THEN insert new one
within the same transaction to maintain the unique constraint on
``(relation_id) WHERE is_current = true``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class RelationSummaryRepository:
    """Write/read repository for ``relation_summaries``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_current(self, relation_id: UUID) -> dict[str, object] | None:
        """Fetch the current summary for a relation (is_current=true)."""
        result = await self._session.execute(
            text("""
SELECT summary_id, summary_text, evidence_count, evidence_hash,
       model_id, prompt_template_id, generated_at, generation_trigger
FROM relation_summaries
WHERE relation_id = :relation_id AND is_current = true
LIMIT 1
"""),
            {"relation_id": str(relation_id)},
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            "summary_id": UUID(str(row[0])),
            "summary_text": row[1],
            "evidence_count": int(row[2]),
            "evidence_hash": row[3],
            "model_id": row[4],
            "prompt_template_id": UUID(str(row[5])),
            "generated_at": row[6],
            "generation_trigger": row[7],
        }

    async def insert_new(
        self,
        relation_id: UUID,
        summary_text: str,
        evidence_count: int,
        evidence_hash: str,
        model_id: str,
        prompt_template_id: UUID,
        generation_trigger: str,
    ) -> UUID:
        """Insert a new current summary, retiring any previous one.

        Pattern (must run in a single transaction):
        1. Set old summaries ``is_current = false``.
        2. Insert new summary with ``is_current = true``.
        """
        # Step 1 — retire old summaries
        await self._session.execute(
            text("""
UPDATE relation_summaries
SET is_current = false
WHERE relation_id = :relation_id AND is_current = true
"""),
            {"relation_id": str(relation_id)},
        )

        # Step 2 — insert new current summary
        result = await self._session.execute(
            text("""
INSERT INTO relation_summaries (
    relation_id, summary_text, evidence_count, evidence_hash,
    model_id, prompt_template_id, is_current, generation_trigger
) VALUES (
    :relation_id, :summary_text, :evidence_count, :evidence_hash,
    :model_id, :prompt_template_id, true, :generation_trigger
)
RETURNING summary_id
"""),
            {
                "relation_id": str(relation_id),
                "summary_text": summary_text,
                "evidence_count": evidence_count,
                "evidence_hash": evidence_hash,
                "model_id": model_id,
                "prompt_template_id": str(prompt_template_id),
                "generation_trigger": generation_trigger,
            },
        )
        row = result.fetchone()
        return UUID(str(row[0]))  # type: ignore[index]

    async def update_embedding(
        self,
        summary_id: UUID,
        embedding: list[float],
    ) -> None:
        """Persist a computed embedding for an existing summary row (Worker 13F)."""
        await self._session.execute(
            text("""
UPDATE relation_summaries
SET summary_embedding = :embedding
WHERE summary_id = :summary_id
"""),
            {"summary_id": str(summary_id), "embedding": embedding},
        )
