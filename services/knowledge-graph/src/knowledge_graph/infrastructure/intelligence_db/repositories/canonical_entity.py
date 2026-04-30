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

    async def get_batch(self, entity_ids: list[UUID]) -> list[dict[str, object]]:
        """Fetch multiple canonical entities in one query.

        Returns only entities that exist; missing IDs are omitted silently.
        """
        if not entity_ids:
            return []
        result = await self._session.execute(
            text("""
SELECT entity_id, canonical_name, entity_type, isin, ticker, exchange, metadata
FROM canonical_entities
WHERE entity_id = ANY(:ids)
"""),
            {"ids": [str(eid) for eid in entity_ids]},
        )
        return [
            {
                "entity_id": UUID(str(row[0])),
                "canonical_name": row[1],
                "entity_type": row[2],
                "isin": row[3],
                "ticker": row[4],
                "exchange": row[5],
                "metadata": row[6],
            }
            for row in result.fetchall()
        ]

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

    async def find_by_ticker(self, ticker: str) -> dict[str, object] | None:
        """Find entity by ticker symbol (case-insensitive exact match).

        Returns the entity dict or None when no entity is seeded for that ticker.
        Used by the gateway to resolve instrument_id → KG entity_id via ticker.
        """
        result = await self._session.execute(
            text("""
SELECT entity_id, canonical_name, entity_type, isin, ticker, exchange, metadata
FROM canonical_entities
WHERE UPPER(ticker) = UPPER(:ticker)
LIMIT 1
"""),
            {"ticker": ticker},
        )
        row = result.fetchone()
        if row is None:
            return None
        return {
            "entity_id": row[0],
            "canonical_name": row[1],
            "entity_type": row[2],
            "isin": row[3],
            "ticker": row[4],
            "exchange": row[5],
            "metadata": row[6],
        }

    async def create(
        self,
        canonical_name: str,
        entity_type: str,
        *,
        entity_id: UUID | None = None,
        isin: str | None = None,
        ticker: str | None = None,
        exchange: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> UUID:
        """Insert a new canonical entity, returning the generated entity_id.

        PLAN-0057 Wave C-5 (T-C-5-01): co-inserts an EXACT self-alias row in the
        same transaction. Without this, callers that bypass the dedicated
        instrument/provisional consumers (e.g. `CreateCanonicalEntityUseCase`)
        would leave the canonical without a Stage-1 alias-exact match for its
        own canonical name. Idempotent via the
        ``uidx_entity_aliases_entity_norm_type`` partial UNIQUE index added by
        migration 0008 (Wave A-2).

        PLAN-0057 QA-iter1 F-DS-03 / F-DATA-04 / F-ARCH-06: callers may pass an
        explicit ``entity_id`` to preserve cross-service stable IDs (M-017).
        For instruments, the canonical's ``entity_id`` MUST equal the
        ``instrument_id`` so portfolio's InstrumentRef.id and KG's canonical
        line up across replays. When omitted we let the column default
        (``gen_random_uuid()``) generate one, which is appropriate for
        non-instrument entities (e.g. provisional canonicals) where there is
        no upstream stable ID.

        PLAN-0057 QA-iter1 F-DS-05 / F-DATA-07: the self-alias INSERT runs
        inside a SAVEPOINT so a collision against the legacy cross-entity
        ``uidx_entity_aliases_normalized`` index (different conflict target
        than the per-entity index referenced by ON CONFLICT) does not abort
        the outer transaction and roll back the canonical we just created.
        """
        import json

        params: dict[str, object | None] = {
            "canonical_name": canonical_name,
            "entity_type": entity_type,
            "isin": isin,
            "ticker": ticker,
            "exchange": exchange,
            "metadata": json.dumps(metadata) if metadata else None,
        }
        if entity_id is not None:
            sql = """
INSERT INTO canonical_entities
    (entity_id, canonical_name, entity_type, isin, ticker, exchange, metadata)
VALUES (:entity_id, :canonical_name, :entity_type, :isin, :ticker, :exchange, :metadata)
ON CONFLICT (entity_id) DO NOTHING
RETURNING entity_id
"""
            params["entity_id"] = str(entity_id)
        else:
            sql = """
INSERT INTO canonical_entities (canonical_name, entity_type, isin, ticker, exchange, metadata)
VALUES (:canonical_name, :entity_type, :isin, :ticker, :exchange, :metadata)
RETURNING entity_id
"""
        result = await self._session.execute(text(sql), params)
        row = result.fetchone()
        if row is None:
            # ON CONFLICT (entity_id) DO NOTHING fired — caller supplied an
            # entity_id that already exists. Return it; the self-alias INSERT
            # below is itself idempotent.
            assert entity_id is not None  # invariant: only ON CONFLICT path with entity_id
            resolved_entity_id = entity_id
        else:
            resolved_entity_id = UUID(str(row[0]))

        # ── EXACT self-alias (PLAN-0057 C-5 / Fix-B.2) ────────────────────────
        # Note: ON CONFLICT target matches the partial UNIQUE index installed by
        # migration 0008 — we MUST repeat the index's WHERE clause for Postgres
        # to use the partial-index path. SAVEPOINT-wrap so a cross-entity EXACT
        # collision against the legacy ``uidx_entity_aliases_normalized`` index
        # cannot poison the outer transaction.
        try:
            async with self._session.begin_nested():
                await self._session.execute(
                    text("""
INSERT INTO entity_aliases
    (entity_id, alias_text, normalized_alias_text, alias_type, is_active, source)
VALUES (:eid, :alias, :norm, 'EXACT', true, 'canonical_entity_create')
ON CONFLICT (entity_id, normalized_alias_text, alias_type)
WHERE is_active = true
DO NOTHING
"""),
                    {
                        "eid": str(resolved_entity_id),
                        "alias": canonical_name,
                        "norm": canonical_name.lower().strip(),
                    },
                )
        except Exception:  # noqa: S110 — cross-entity EXACT collision is recoverable
            # The canonical was successfully created and the cross-entity EXACT
            # alias just couldn't be inserted; that's an acceptable degraded
            # state (the canonical is reachable by entity_id, just not by
            # exact-alias text match against this exact spelling).
            pass
        return resolved_entity_id
