"""EntityAlias repository — queries against intelligence_db.entity_aliases.

Uses raw SQL (text()) — S6 does not own intelligence_db DDL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class EntityAliasRepository:
    """Lookup entity aliases in intelligence_db (PRD §6.7 Block 9)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def exact_match(self, mention_text: str) -> UUID | None:
        """Stage 1 — exact alias match. Confidence: 1.0."""
        result = await self._session.execute(
            text(
                "SELECT entity_id FROM entity_aliases "
                "WHERE normalized_alias_text = lower(trim(:mention_text)) "
                "AND alias_type = 'EXACT' AND is_active = true "
                "LIMIT 1",
            ),
            {"mention_text": mention_text},
        )
        row = result.fetchone()
        return UUID(str(row[0])) if row else None

    async def ticker_isin_match(
        self,
        ticker: str | None,
        isin: str | None,
        exchange: str | None = None,
    ) -> UUID | None:
        """Stage 2 — ticker/ISIN match against canonical_entities. Confidence: 0.95."""
        if ticker:
            result = await self._session.execute(
                text(
                    "SELECT entity_id FROM canonical_entities "
                    "WHERE ticker = :ticker "
                    "AND (:exchange IS NULL OR exchange = :exchange) "
                    "LIMIT 1",
                ),
                {"ticker": ticker, "exchange": exchange},
            )
            row = result.fetchone()
            if row:
                return UUID(str(row[0]))
        if isin:
            result = await self._session.execute(
                text("SELECT entity_id FROM canonical_entities WHERE isin = :isin LIMIT 1"),
                {"isin": isin},
            )
            row = result.fetchone()
            if row:
                return UUID(str(row[0]))
        return None

    async def fuzzy_trigram(
        self,
        mention_text: str,
        threshold: float = 0.75,
        top_k: int = 5,
    ) -> list[tuple[UUID, float]]:
        """Stage 3 — fuzzy trigram similarity via pg_trgm. Confidence: sim * 0.90."""
        result = await self._session.execute(
            text(
                "SELECT entity_id, similarity(normalized_alias_text, lower(:mention_text)) AS sim "
                "FROM entity_aliases "
                "WHERE similarity(normalized_alias_text, lower(:mention_text)) > :threshold "
                "AND is_active = true "
                "ORDER BY sim DESC "
                "LIMIT :top_k",
            ),
            {"mention_text": mention_text, "threshold": threshold, "top_k": top_k},
        )
        return [(UUID(str(row[0])), float(row[1])) for row in result.fetchall()]
