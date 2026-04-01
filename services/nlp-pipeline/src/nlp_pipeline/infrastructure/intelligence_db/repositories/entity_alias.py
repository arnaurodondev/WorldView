"""EntityAlias repository — queries against intelligence_db.entity_aliases.

Uses raw SQL (text()) — S6 does not own intelligence_db DDL.

Batch methods (batch_exact_match, batch_ticker_isin_match, batch_fuzzy_trigram)
execute one query per stage for N mentions, reducing latency from O(N) to O(1)
per stage.  Use these when resolving more than one mention at a time.
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

    # ── Single-mention helpers (kept for compatibility) ───────────────────────

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

    # ── Batch helpers (1 query for N mentions — use these in production paths) ─

    async def batch_exact_match(
        self,
        mention_texts: list[str],
    ) -> dict[str, UUID]:
        """Stage 1 batch — return {normalized_text: entity_id} for all exact matches.

        One SQL query regardless of how many mentions are passed.
        """
        if not mention_texts:
            return {}
        # Build a VALUES list: (lower(trim(text1)), lower(trim(text2)), ...)
        normalized = [t.lower().strip() for t in mention_texts]
        placeholders = ", ".join(f":t{i}" for i in range(len(normalized)))
        params = {f"t{i}": v for i, v in enumerate(normalized)}
        result = await self._session.execute(
            text(
                f"SELECT normalized_alias_text, entity_id "
                f"FROM entity_aliases "
                f"WHERE normalized_alias_text IN ({placeholders}) "
                f"AND alias_type = 'EXACT' AND is_active = true",
            ),
            params,
        )
        return {str(row[0]): UUID(str(row[1])) for row in result.fetchall()}

    async def batch_ticker_isin_match(
        self,
        tickers: list[str],
        isins: list[str],
    ) -> dict[str, UUID]:
        """Stage 2 batch — return {ticker_or_isin: entity_id} for all matches.

        One SQL query for tickers + one for ISINs (only if non-empty inputs).
        """
        out: dict[str, UUID] = {}
        if tickers:
            placeholders = ", ".join(f":tk{i}" for i in range(len(tickers)))
            params = {f"tk{i}": v for i, v in enumerate(tickers)}
            result = await self._session.execute(
                text(
                    f"SELECT ticker, entity_id FROM canonical_entities WHERE ticker IN ({placeholders})",
                ),
                params,
            )
            for row in result.fetchall():
                out[str(row[0])] = UUID(str(row[1]))
        if isins:
            placeholders = ", ".join(f":is{i}" for i in range(len(isins)))
            params = {f"is{i}": v for i, v in enumerate(isins)}
            result = await self._session.execute(
                text(
                    f"SELECT isin, entity_id FROM canonical_entities WHERE isin IN ({placeholders})",
                ),
                params,
            )
            for row in result.fetchall():
                out[str(row[0])] = UUID(str(row[1]))
        return out

    async def batch_fuzzy_trigram(
        self,
        mention_texts: list[str],
        threshold: float = 0.75,
        top_k_per_mention: int = 5,
    ) -> dict[str, list[tuple[UUID, float]]]:
        """Stage 3 batch — return best fuzzy matches per mention text.

        Issues one parameterised LATERAL query for all mentions.
        Returns {normalized_text: [(entity_id, similarity), ...]}.
        """
        if not mention_texts:
            return {}
        normalized = [t.lower().strip() for t in mention_texts]
        # Use UNNEST to pass all search terms in one round-trip
        result = await self._session.execute(
            text(
                "SELECT q.search_term, ea.entity_id, "
                "similarity(ea.normalized_alias_text, q.search_term) AS sim "
                "FROM unnest(:terms::text[]) AS q(search_term) "
                "JOIN entity_aliases ea ON "
                "  similarity(ea.normalized_alias_text, q.search_term) > :threshold "
                "  AND ea.is_active = true "
                "ORDER BY q.search_term, sim DESC",
            ),
            {"terms": normalized, "threshold": threshold},
        )
        # Group results by search term, keep top_k per mention
        out: dict[str, list[tuple[UUID, float]]] = {}
        for row in result.fetchall():
            term = str(row[0])
            entries = out.setdefault(term, [])
            if len(entries) < top_k_per_mention:
                entries.append((UUID(str(row[1])), float(row[2])))
        return out
