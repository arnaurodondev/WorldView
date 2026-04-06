"""CanonicalEntity repository for S7 — read-only access (PRD §6.4.4).

Uses raw SQL via ``text()`` — S7 does not own intelligence_db DDL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class CanonicalEntityRepository:
    """Read-only repository for ``canonical_entities`` in intelligence_db."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, entity_id: UUID) -> dict[str, object] | None:
        """Fetch a canonical entity by ID."""
        result = await self._session.execute(
            text("""
SELECT entity_id, canonical_name, entity_type, isin, ticker, exchange, metadata
FROM canonical_entities
WHERE entity_id = :entity_id
"""),
            {"entity_id": str(entity_id)},
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            "entity_id": UUID(str(row[0])),
            "canonical_name": row[1],
            "entity_type": row[2],
            "isin": row[3],
            "ticker": row[4],
            "exchange": row[5],
            "metadata": row[6],
        }

    async def exists(self, entity_id: UUID) -> bool:
        """Check whether a canonical entity exists."""
        result = await self._session.execute(
            text("SELECT 1 FROM canonical_entities WHERE entity_id = :entity_id"),
            {"entity_id": str(entity_id)},
        )
        return result.fetchone() is not None

    async def find_by_name_and_type(self, canonical_name: str, entity_type: str) -> UUID | None:
        """Find entity_id by exact canonical_name + entity_type match.

        Used by FundamentalsRefreshWorker to resolve GICS sector/industry entities.
        Returns None if not found (e.g. unsupported sector name, seed not applied).
        """
        result = await self._session.execute(
            text("""
SELECT entity_id FROM canonical_entities
WHERE canonical_name = :canonical_name AND entity_type = :entity_type
"""),
            {"canonical_name": canonical_name, "entity_type": entity_type},
        )
        row = result.fetchone()
        return UUID(str(row[0])) if row else None

    async def create(
        self,
        canonical_name: str,
        entity_type: str,
        *,
        isin: str | None = None,
        ticker: str | None = None,
        exchange: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> UUID:
        """Insert a new canonical entity, returning the generated entity_id."""
        import json

        result = await self._session.execute(
            text("""
INSERT INTO canonical_entities (canonical_name, entity_type, isin, ticker, exchange, metadata)
VALUES (:canonical_name, :entity_type, :isin, :ticker, :exchange, :metadata)
RETURNING entity_id
"""),
            {
                "canonical_name": canonical_name,
                "entity_type": entity_type,
                "isin": isin,
                "ticker": ticker,
                "exchange": exchange,
                "metadata": json.dumps(metadata) if metadata else None,
            },
        )
        row = result.fetchone()
        return UUID(str(row[0]))  # type: ignore[index]
