"""EntityRepository — write-oriented canonical entity operations for EODHD enrichment.

Complements :class:`CanonicalEntityRepository` (read-only) with mutation
operations used by EODHD enrichment workers (Wave B-1/B-3/B-4).

Uses raw SQL via ``text()`` — S7 does not own intelligence_db DDL.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class EntityRepository:
    """Write-oriented repository for ``canonical_entities`` in intelligence_db.

    Provides partial metadata patch and entity upsert operations used by
    EODHD enrichment workers (FundamentalsConsumer, MacroIndicatorWorker,
    InsiderTransactionsWorker).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def update_metadata(
        self,
        entity_id: UUID,
        updates: dict[str, object],
    ) -> None:
        """Partially patch ``canonical_entities.metadata`` — merges, does not replace.

        Uses PostgreSQL JSONB ``||`` operator: existing keys not present in *updates*
        are preserved; new keys are added; existing keys in *updates* are overwritten.
        No-op if the entity does not exist.

        Args:
            entity_id: Target canonical entity UUID.
            updates:   Key/value pairs to merge into the existing metadata JSONB.
        """
        await self._session.execute(
            text("""
UPDATE canonical_entities
SET metadata = COALESCE(metadata, '{}'::jsonb) || cast(:updates AS jsonb)
WHERE entity_id = :entity_id
"""),
            {
                "entity_id": str(entity_id),
                "updates": json.dumps(updates),
            },
        )

    async def find_country_entity(self, iso2: str) -> UUID | None:
        """Find the canonical entity_id for a country by ISO-3166 alpha-2 code.

        Looks up ``canonical_entities`` where ``entity_type = 'country'`` and
        ``metadata->>'country_iso' = :iso2``.

        Returns ``None`` if no country entity is found (e.g. the entity has not
        been seeded or the ISO-2 code is not tracked).

        Args:
            iso2: ISO-3166 alpha-2 country code (e.g. ``"US"``, ``"DE"``).
        """
        from uuid import UUID as _UUID

        result = await self._session.execute(
            text("""
SELECT entity_id FROM canonical_entities
WHERE entity_type = 'country'
  AND metadata->>'country_iso' = :iso2
LIMIT 1
"""),
            {"iso2": iso2},
        )
        row = result.fetchone()
        return _UUID(str(row[0])) if row else None
