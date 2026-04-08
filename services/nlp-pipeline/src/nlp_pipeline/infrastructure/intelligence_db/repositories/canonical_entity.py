"""CanonicalEntity repository — get/create in intelligence_db.

Uses raw SQL (text()) — S6 does not own intelligence_db DDL.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

import common.ids  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class CanonicalEntityRepository:
    """Read/create canonical entities in intelligence_db (PRD §6.7 Block 9)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, entity_id: UUID) -> dict[str, object] | None:
        """Fetch a canonical entity by ID."""
        result = await self._session.execute(
            text(
                "SELECT entity_id, canonical_name, entity_type, isin, ticker, exchange "
                "FROM canonical_entities WHERE entity_id = :entity_id",
            ),
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
        }

    async def batch_get(self, entity_ids: list[UUID]) -> dict[UUID, dict[str, object]]:
        """Fetch multiple canonical entities by ID in a single query.

        Returns a dict keyed by entity_id; missing IDs are omitted.
        """
        if not entity_ids:
            return {}

        result = await self._session.execute(
            text(
                "SELECT entity_id, canonical_name, entity_type, isin, ticker, exchange "
                "FROM canonical_entities WHERE entity_id = ANY(:ids)",
            ),
            {"ids": [str(eid) for eid in entity_ids]},
        )
        rows = result.fetchall()
        return {
            UUID(str(row[0])): {
                "entity_id": UUID(str(row[0])),
                "canonical_name": row[1],
                "entity_type": row[2],
                "isin": row[3],
                "ticker": row[4],
                "exchange": row[5],
            }
            for row in rows
        }

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
        """Insert a new canonical entity and return its ID."""
        entity_id = common.ids.new_uuid7()
        now = datetime.now(tz=UTC)
        await self._session.execute(
            text(
                "INSERT INTO canonical_entities "
                "(entity_id, canonical_name, entity_type, isin, ticker, exchange, metadata, "
                "created_at, updated_at) "
                "VALUES (:entity_id, :canonical_name, :entity_type, :isin, :ticker, :exchange, "
                "cast(:metadata AS jsonb), :created_at, :updated_at)",
            ),
            {
                "entity_id": str(entity_id),
                "canonical_name": canonical_name,
                "entity_type": entity_type,
                "isin": isin,
                "ticker": ticker,
                "exchange": exchange,
                "metadata": None if metadata is None else str(metadata),
                "created_at": now,
                "updated_at": now,
            },
        )
        return entity_id
