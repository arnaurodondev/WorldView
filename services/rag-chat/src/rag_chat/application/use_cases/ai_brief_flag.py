"""GetAiBriefFlagUseCase — PLAN-0089 Wave L-5a (T-WL5A-03).

Returns whether any cached entity-scoped AI brief exists for
``instrument_id``. Used by the screener S3-side sync worker (Wave L-5b) to
materialise ``instrument_intelligence_snapshot.has_ai_brief`` +
``ai_brief_generated_at``.

Brief source choice (audit §8.b — "cached public/instrument briefs"):
  - We surface the existence of any ``user_briefs`` row whose
    ``brief_type='entity'`` AND ``entity_id == instrument_id``, regardless
    of which user generated it. From the screener's POV the "AI brief"
    column is a per-entity coverage indicator ("has anyone in the system
    generated a brief for this instrument?"), not a per-user attribute.
  - User-keyed morning briefs (``brief_type='morning'`` with
    ``entity_id IS NULL``) are EXCLUDED — they are user-scoped journals,
    not instrument-scoped content.

Future Valkey-cached daily_briefings keyed by instrument could also be
checked here, but no such cache exists today; the ``user_briefs`` table
is the only authoritative entity-scoped brief store.

R9: reads only from ``rag_chat_db`` (S8's own DB).
R25: API → use case only.
R27: caller wires a read-only UoW / session.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class AiBriefFlag:
    """Small JSON-friendly DTO returned by the use case."""

    has_ai_brief: bool
    brief_generated_at: datetime | None


class GetAiBriefFlagUseCase:
    """Probe ``user_briefs`` for the most-recent entity-scoped brief."""

    async def execute(
        self,
        session: AsyncSession,
        instrument_id: UUID,
    ) -> AiBriefFlag:
        """Return the latest entity-brief timestamp for ``instrument_id`` (or None)."""
        sql = text(
            """
            SELECT MAX(generated_at) AS latest_at
            FROM user_briefs
            WHERE brief_type = 'entity'
              AND entity_id = :entity_id
            """,
        )
        result = await session.execute(sql, {"entity_id": str(instrument_id)})
        row = result.fetchone()
        latest_at = row[0] if row is not None else None
        return AiBriefFlag(
            has_ai_brief=latest_at is not None,
            brief_generated_at=latest_at,
        )
