"""EntityAlias repository (PRD §6.7 Block 13D-4 / 13E).

Uses raw SQL via ``text()`` — S7 does not own intelligence_db DDL.

Alias types used by S7:
  - 'EXACT'   — canonical name (unique when active, normalized)
  - 'TICKER'  — exchange:ticker (e.g. "NASDAQ:AAPL")
  - 'ISIN'    — ISIN code
  - 'NAME'    — common name variants
  - 'LLM'     — LLM-generated supplementary aliases (may collide → reject)
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class EntityAliasRepository:
    """Read/write repository for ``entity_aliases``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_exact(self, normalized_alias_text: str) -> dict[str, object] | None:
        """Find the entity owning an active EXACT alias (primary lookup path)."""
        result = await self._session.execute(
            text("""
SELECT ea.alias_id, ea.entity_id, ea.alias_text, ea.alias_type, ea.source
FROM entity_aliases ea
WHERE ea.normalized_alias_text = :normalized
  AND ea.alias_type             = 'EXACT'
  AND ea.is_active              = true
LIMIT 1
"""),
            {"normalized": normalized_alias_text},
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            "alias_id": UUID(str(row[0])),
            "entity_id": UUID(str(row[1])),
            "alias_text": row[2],
            "alias_type": row[3],
            "source": row[4],
        }

    async def find_by_normalized_and_type(
        self,
        normalized_alias_text: str,
        alias_type: str,
    ) -> dict[str, object] | None:
        """Find an active alias by normalized text and type (TICKER / ISIN lookups)."""
        result = await self._session.execute(
            text("""
SELECT alias_id, entity_id, alias_text, alias_type, source
FROM entity_aliases
WHERE normalized_alias_text = :normalized
  AND alias_type             = :alias_type
  AND is_active              = true
LIMIT 1
"""),
            {"normalized": normalized_alias_text, "alias_type": alias_type},
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            "alias_id": UUID(str(row[0])),
            "entity_id": UUID(str(row[1])),
            "alias_text": row[2],
            "alias_type": row[3],
            "source": row[4],
        }

    async def insert(
        self,
        entity_id: UUID,
        alias_text: str,
        normalized_alias_text: str,
        alias_type: str,
        source: str | None = None,
    ) -> UUID | None:
        """Insert a new alias row, returning alias_id (None on any conflict).

        The entity_aliases table has TWO unique indexes that can fire:
          1. uidx_entity_aliases_entity_norm_type — per-entity partial index
             (entity_id, normalized_alias_text, alias_type) WHERE is_active=true.
             Handled by the ON CONFLICT clause below (same entity, same alias → skip).
          2. uidx_entity_aliases_normalized — global EXACT index
             (normalized_alias_text) WHERE alias_type='EXACT' AND is_active=true.
             NOT handled by ON CONFLICT (different entity owns the alias).

        BP-449 fix: wraps the INSERT in a SAVEPOINT (begin_nested) so that a
        UniqueViolationError from either index is caught without aborting the outer
        session transaction. Returns None in both conflict cases. Callers that
        already use their own begin_nested (e.g. instrument_consumer._try_insert_alias)
        are unaffected — nested SAVEPOINTs work correctly in Postgres/SQLAlchemy.
        """
        try:
            async with self._session.begin_nested():
                result = await self._session.execute(
                    text("""
INSERT INTO entity_aliases (entity_id, alias_text, normalized_alias_text, alias_type, source)
VALUES (:entity_id, :alias_text, :normalized_alias_text, :alias_type, :source)
ON CONFLICT (entity_id, normalized_alias_text, alias_type)
WHERE is_active = true
DO NOTHING
RETURNING alias_id
"""),
                    {
                        "entity_id": str(entity_id),
                        "alias_text": alias_text,
                        "normalized_alias_text": normalized_alias_text,
                        "alias_type": alias_type,
                        "source": source,
                    },
                )
                row = result.fetchone()
                return UUID(str(row[0])) if row else None
        except IntegrityError as exc:
            pgcode = getattr(getattr(exc, "orig", None), "pgcode", None)
            if pgcode == "23505":
                # Global uidx_entity_aliases_normalized fired — a different entity
                # already owns this EXACT alias. Treat as soft conflict: skip.
                return None
            raise

    async def get_for_entity(self, entity_id: UUID) -> list[dict[str, object]]:
        """Fetch all active aliases for an entity."""
        result = await self._session.execute(
            text("""
SELECT alias_id, alias_text, normalized_alias_text, alias_type, source, created_at
FROM entity_aliases
WHERE entity_id = :entity_id AND is_active = true
ORDER BY alias_type, alias_text
"""),
            {"entity_id": str(entity_id)},
        )
        rows = result.fetchall()
        return [
            {
                "alias_id": UUID(str(r[0])),
                "alias_text": r[1],
                "normalized_alias_text": r[2],
                "alias_type": r[3],
                "source": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]

    async def fuzzy_search(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, object]]:
        """Trigram similarity search against active aliases (GIN index required).

        Returns aliases ordered by similarity descending.
        """
        # WHY single % not %%: SQLAlchemy text() does NOT format % signs; asyncpg
        # sends the SQL verbatim to PostgreSQL. The pg_trgm similarity operator is
        # the single-percent character (%). Using %% was a bug — PostgreSQL saw the
        # literal string "%%" which is not a recognized operator.
        # BP-448 class: asyncpg infers :query as `text`; explicit CAST to varchar
        # matches the `character varying` column type for the % operator.
        result = await self._session.execute(
            text(
                "SELECT alias_id, entity_id, alias_text, normalized_alias_text, alias_type,"
                "       similarity(normalized_alias_text, CAST(:query AS varchar)) AS sim"
                " FROM entity_aliases"
                " WHERE normalized_alias_text % CAST(:query AS varchar)"
                "   AND is_active = true"
                " ORDER BY sim DESC"
                " LIMIT :limit",
            ),
            {"query": query, "limit": limit},
        )
        rows = result.fetchall()
        return [
            {
                "alias_id": UUID(str(r[0])),
                "entity_id": UUID(str(r[1])),
                "alias_text": r[2],
                "normalized_alias_text": r[3],
                "alias_type": r[4],
                "similarity": float(r[5]),
            }
            for r in rows
        ]
