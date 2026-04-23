"""EntityEmbeddingState repository (PRD §6.7 Block 13D).

Uses raw SQL via ``text()`` — S7 does not own intelligence_db DDL.

View-row allocation per entity type (PRD-0017 §6.5):
  - financial_instrument  → 3 rows: definition, narrative, fundamentals_ohlcv
  - all other types       → 2 rows: definition, narrative only

Non-company entities have no structured fundamentals data; creating a
fundamentals_ohlcv row for them wastes storage and pollutes ANN results.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# View type constants
VIEW_DEFINITION = "definition"
VIEW_NARRATIVE = "narrative"
VIEW_FUNDAMENTALS = "fundamentals_ohlcv"

# All 3 view types (for financial_instrument entities and internal iteration)
ALL_VIEW_TYPES = (VIEW_DEFINITION, VIEW_NARRATIVE, VIEW_FUNDAMENTALS)

# Non-company entities get only definition + narrative (no fundamentals data)
COMPANY_VIEW_TYPES = ALL_VIEW_TYPES
NON_COMPANY_VIEW_TYPES = (VIEW_DEFINITION, VIEW_NARRATIVE)

# Entity types that receive fundamentals_ohlcv embeddings
COMPANY_ENTITY_TYPES: frozenset[str] = frozenset({"financial_instrument"})


def get_view_types_for_entity_type(entity_type: str) -> tuple[str, ...]:
    """Return the view types to provision for a given entity type.

    - ``financial_instrument`` → (definition, narrative, fundamentals_ohlcv)
    - all other types          → (definition, narrative)
    """
    if entity_type in COMPANY_ENTITY_TYPES:
        return COMPANY_VIEW_TYPES
    return NON_COMPANY_VIEW_TYPES


def sha256_hex(text_content: str) -> str:
    """Return SHA-256 hex digest of a UTF-8 string."""
    return hashlib.sha256(text_content.encode()).hexdigest()


class EntityEmbeddingStateRepository:
    """Read/write repository for ``entity_embedding_state`` (multi-view embeddings)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        entity_id: UUID,
        view_type: str,
        *,
        embedding: list[float] | None,
        model_id: str | None,
        source_text: str | None,
        source_hash: str | None,
        next_refresh_at: datetime | None,
    ) -> None:
        """Upsert an embedding row for (entity_id, view_type).

        Increments ``refresh_count`` on each update.
        """
        await self._session.execute(
            text("""
INSERT INTO entity_embedding_state (
    entity_id, view_type, embedding, model_id, source_text, source_hash,
    last_refreshed_at, next_refresh_at, refresh_count
) VALUES (
    :entity_id, :view_type, :embedding, :model_id, :source_text, :source_hash,
    now(), :next_refresh_at, 0
)
ON CONFLICT (entity_id, view_type) DO UPDATE SET
    embedding         = COALESCE(EXCLUDED.embedding, entity_embedding_state.embedding),
    model_id          = COALESCE(EXCLUDED.model_id, entity_embedding_state.model_id),
    source_text       = EXCLUDED.source_text,
    source_hash       = EXCLUDED.source_hash,
    last_refreshed_at = now(),
    next_refresh_at   = EXCLUDED.next_refresh_at,
    refresh_count     = entity_embedding_state.refresh_count + 1
"""),
            {
                "entity_id": str(entity_id),
                "view_type": view_type,
                "embedding": embedding,
                "model_id": model_id,
                "source_text": source_text,
                "source_hash": source_hash,
                "next_refresh_at": next_refresh_at,
            },
        )

    async def get(self, entity_id: UUID, view_type: str) -> dict[str, object] | None:
        """Fetch a single embedding row by primary key."""
        result = await self._session.execute(
            text("""
SELECT entity_id, view_type, model_id, source_hash,
       last_refreshed_at, next_refresh_at, refresh_count
FROM entity_embedding_state
WHERE entity_id = :entity_id AND view_type = :view_type
"""),
            {"entity_id": str(entity_id), "view_type": view_type},
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            "entity_id": UUID(str(row[0])),
            "view_type": row[1],
            "model_id": row[2],
            "source_hash": row[3],
            "last_refreshed_at": row[4],
            "next_refresh_at": row[5],
            "refresh_count": int(row[6]),
        }

    async def count_for_entity(self, entity_id: UUID) -> int:
        """Count rows for an entity (2 for non-company entities, 3 for financial_instrument)."""
        result = await self._session.execute(
            text("SELECT COUNT(*) FROM entity_embedding_state WHERE entity_id = :entity_id"),
            {"entity_id": str(entity_id)},
        )
        row = result.fetchone()
        return int(row[0]) if row else 0  # type: ignore[index]

    async def ensure_rows_exist(self, entity_id: UUID, entity_type: str) -> None:
        """Ensure the correct view-type rows exist for an entity (null embeddings ok).

        - ``financial_instrument``: 3 rows (definition, narrative, fundamentals_ohlcv)
        - all other types:          2 rows (definition, narrative)

        Uses ``ON CONFLICT DO NOTHING`` for idempotency.
        """
        for vt in get_view_types_for_entity_type(entity_type):
            await self._session.execute(
                text("""
INSERT INTO entity_embedding_state (entity_id, view_type, last_refreshed_at, refresh_count)
VALUES (:entity_id, :view_type, now(), 0)
ON CONFLICT (entity_id, view_type) DO NOTHING
"""),
                {"entity_id": str(entity_id), "view_type": vt},
            )

    async def get_due_for_refresh(
        self,
        view_type: str,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        """Fetch entities whose embedding is due for refresh (next_refresh_at < now())."""
        result = await self._session.execute(
            text("""
SELECT ees.entity_id, ees.source_hash, ees.source_text, ce.canonical_name,
       ce.entity_type, ce.ticker, ce.isin, ce.exchange
FROM entity_embedding_state ees
JOIN canonical_entities ce ON ce.entity_id = ees.entity_id
WHERE ees.view_type       = :view_type
  AND ees.next_refresh_at IS NOT NULL
  AND ees.next_refresh_at  < now()
ORDER BY ees.next_refresh_at
LIMIT :limit
FOR UPDATE OF ees SKIP LOCKED
"""),
            {"view_type": view_type, "limit": limit},
        )
        rows = result.fetchall()
        return [
            {
                "entity_id": UUID(str(r[0])),
                "source_hash": r[1],
                "source_text": r[2],
                "canonical_name": r[3],
                "entity_type": r[4],
                "ticker": r[5],
                "isin": r[6],
                "exchange": r[7],
            }
            for r in rows
        ]
